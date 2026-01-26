from django.http import JsonResponse
from rest_framework import viewsets, permissions, status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.response import Response
from rest_framework.decorators import action, api_view, permission_classes
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Sum, Q
import requests

from .models import Classroom, Deck, Card, Test, Progress
from .utils import download_from_appwrite, parse_anki_file, get_primary_deck_name
import tempfile
import os
from .serializers import (
    ClassroomSerializer,
    ClassroomDetailSerializer,
    DeckSerializer,
    TestSerializer,
    TestSerializer,
    ProgressSerializer,
    SupportTicketSerializer,
)

User = get_user_model()


def index(request):
    return JsonResponse({"status": "ok", "message": "LMS API is running"})


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def dashboard_stats(request):
    """Return dashboard statistics for teacher."""
    user = request.user
    
    if user.role != "teacher":
        return Response({"error": "Only teachers can access this"}, status=status.HTTP_403_FORBIDDEN)
    
    # Count students from all classes
    total_students = 0
    for classroom in Classroom.objects.filter(teacher=user):
        total_students += classroom.students.count()
    
    # Count decks
    total_decks = Deck.objects.filter(teacher=user).count()
    
    # Calculate average score from test submissions
    tests = Test.objects.filter(teacher=user)
    from .models import TestSubmission
    submissions = TestSubmission.objects.filter(test__in=tests)
    
    avg_score = 0
    if submissions.exists():
        avg_score = round(submissions.aggregate(avg=models.Avg('score'))['avg'] or 0, 2)
    
    # Count pending assignments/tests
    pending_assignments = tests.filter(status="PENDING").count()
    
    return Response({
        "total_students": total_students,
        "total_decks": total_decks,
        "average_score": avg_score,
        "pending_assignments": pending_assignments,
    })


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def gamification_stats(request):
    """Get current user's gamification stats: XP, Level, Coins, Shields."""
    from .models import CoinTransaction
    from .serializers import CoinTransactionSerializer
    
    user = request.user
    
    # Get recent transactions (last 10)
    transactions = CoinTransaction.objects.filter(user=user)[:10]
    
    return Response({
        "xp": user.xp,
        "level": user.level,
        "coin_balance": user.coin_balance,
        "shield_count": user.shield_count,
        "xp_progress": user.xp_progress(),
        "xp_for_next_level": user.xp_for_next_level(),
        "recent_transactions": CoinTransactionSerializer(transactions, many=True).data
    })


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def buy_shield(request):
    """Buy a streak shield with coins (25 coins each)."""
    user = request.user
    
    if user.buy_shield():
        return Response({
            "message": "Mua Khiên thành công!",
            "shield_count": user.shield_count,
            "coin_balance": user.coin_balance
        })
    else:
        return Response({
            "error": "Không đủ Coin. Cần 25 Coin để mua 1 Khiên."
        }, status=status.HTTP_400_BAD_REQUEST)


class IsTeacher(permissions.BasePermission):
    """Chỉ cho phép Teacher truy cập."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == "teacher"


class ClassroomViewSet(viewsets.ModelViewSet):
    """API endpoint cho Classroom (classes)."""
    serializer_class = ClassroomSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == "teacher":
            return Classroom.objects.filter(teacher=user)
        return Classroom.objects.filter(students=user)

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ClassroomDetailSerializer
        return ClassroomSerializer

    def perform_create(self, serializer):
        serializer.save(teacher=self.request.user)

    @action(detail=True, methods=["post"], url_path="add_student")
    def add_student(self, request, pk=None):
        """Thêm học sinh vào lớp bằng email."""
        classroom = self.get_object()
        email = request.data.get("email")
        
        if not email:
            return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            student = User.objects.get(email=email, role="student")
        except User.DoesNotExist:
            return Response({"error": "Student not found"}, status=status.HTTP_404_NOT_FOUND)
        
        if student in classroom.students.all():
            return Response({"error": "Student already in class"}, status=status.HTTP_400_BAD_REQUEST)
        
        classroom.students.add(student)
        return Response({"message": "Student added successfully"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="remove_student")
    def remove_student(self, request, pk=None):
        """Xóa học sinh khỏi lớp."""
        classroom = self.get_object()
        student_id = request.data.get("student_id")
        
        if not student_id:
            return Response({"error": "Student ID is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            student = User.objects.get(id=student_id)
        except User.DoesNotExist:
            return Response({"error": "Student not found"}, status=status.HTTP_404_NOT_FOUND)
        
        classroom.students.remove(student)
        return Response({"message": "Student removed successfully"}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="add_deck")
    def add_deck(self, request, pk=None):
        """Thêm deck vào lớp và tự động inject vào collection của students."""
        classroom = self.get_object()
        deck_id = request.data.get("deck_id")
        
        if not deck_id:
            return Response({"error": "Deck ID is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            deck = Deck.objects.get(id=deck_id)
        except Deck.DoesNotExist:
            return Response({"error": "Deck not found"}, status=status.HTTP_404_NOT_FOUND)

        if deck in classroom.decks.all():
            return Response({"error": "Deck already in class"}, status=status.HTTP_400_BAD_REQUEST)
            
        classroom.decks.add(deck)
        
        # === INJECT DECK INTO STUDENT COLLECTIONS ===
        injection_results = {"success": [], "failed": [], "not_synced": []}
        
        if deck.appwrite_file_id and deck.appwrite_file_id not in ['pending', 'local_upload']:
            try:
                from .services.deck_injector import inject_deck_to_student
                from django.conf import settings
                
                # Handle local files (format: local:filename.apkg)
                if deck.appwrite_file_id.startswith('local:'):
                    filename = deck.appwrite_file_id.replace('local:', '')
                    local_path = os.path.join(settings.MEDIA_ROOT, 'decks', filename)
                    
                    if not os.path.exists(local_path):
                        raise FileNotFoundError(f"Local deck file not found: {local_path}")
                    
                    with open(local_path, 'rb') as f:
                        deck_content = f.read()
                else:
                    # Download from Appwrite
                    from .utils import download_from_appwrite
                    import tempfile
                    
                    with tempfile.NamedTemporaryFile(suffix='.apkg', delete=False) as tmp:
                        tmp_path = tmp.name
                    
                    download_from_appwrite(deck.appwrite_file_id, tmp_path)
                    
                    with open(tmp_path, 'rb') as f:
                        deck_content = f.read()
                    
                    os.unlink(tmp_path)
                
                # Inject to each student in class
                for student in classroom.students.all():
                    success, message = inject_deck_to_student(student.email, deck_content)
                    if success:
                        injection_results["success"].append(student.email)
                    elif "has not synced" in message:
                        injection_results["not_synced"].append(student.email)
                    else:
                        injection_results["failed"].append({"email": student.email, "error": message})
                        
            except Exception as e:
                import logging
                logging.error(f"Deck injection error: {e}")
        
        return Response({
            "message": "Deck added to class",
            "injection": {
                "injected": len(injection_results["success"]),
                "not_synced_yet": len(injection_results["not_synced"]),
                "failed": len(injection_results["failed"]),
                "details": injection_results
            }
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="remove_deck")
    def remove_deck(self, request, pk=None):
        """Xóa deck khỏi lớp."""
        classroom = self.get_object()
        deck_id = request.data.get("deck_id")
        
        if not deck_id:
            return Response({"error": "Deck ID is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        deck = Deck.objects.filter(id=deck_id).first()
        if not deck:
             return Response({"error": "Deck not found"}, status=status.HTTP_404_NOT_FOUND)

        classroom.decks.remove(deck)
        return Response({"message": "Deck removed from class"}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="preview")
    def preview(self, request):
        """Preview class info by join code (for students before joining)."""
        code = request.query_params.get("code", "").upper()
        
        if not code:
            return Response({"error": "Code is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            classroom = Classroom.objects.get(join_code=code, status="ACTIVE")
        except Classroom.DoesNotExist:
            return Response({"error": "Không tìm thấy lớp học với mã này"}, status=status.HTTP_404_NOT_FOUND)
        
        return Response({
            "id": classroom.id,
            "name": classroom.name,
            "teacher_name": classroom.teacher.full_name if hasattr(classroom.teacher, 'full_name') else classroom.teacher.email,
            "student_count": classroom.students.count(),
        })

    @action(detail=False, methods=["post"], url_path="join")
    def join_class(self, request):
        """Student requests to join a class using join code (requires teacher approval)."""
        from .models import ClassroomJoinRequest
        
        user = request.user
        
        # Only students can join
        if user.role != "student":
            return Response({"error": "Only students can join classes"}, status=status.HTTP_403_FORBIDDEN)
        
        code = request.data.get("code", "").upper()
        message = request.data.get("message", "")  # Optional message from student
        
        if not code:
            return Response({"error": "Code is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            classroom = Classroom.objects.get(join_code=code, status="ACTIVE")
        except Classroom.DoesNotExist:
            return Response({"error": "Không tìm thấy lớp học với mã này"}, status=status.HTTP_404_NOT_FOUND)
        
        # Check if already joined
        if user in classroom.students.all():
            return Response({"error": "Bạn đã tham gia lớp này rồi"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if already has pending request
        existing_request = ClassroomJoinRequest.objects.filter(
            classroom=classroom, student=user, status="PENDING"
        ).first()
        if existing_request:
            return Response({
                "error": "Bạn đã gửi yêu cầu tham gia lớp này rồi. Vui lòng chờ giáo viên phê duyệt.",
                "request_id": existing_request.id
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if was previously rejected
        rejected_request = ClassroomJoinRequest.objects.filter(
            classroom=classroom, student=user, status="REJECTED"
        ).first()
        if rejected_request:
            # Update existing rejected request to pending
            rejected_request.status = "PENDING"
            rejected_request.message = message
            rejected_request.reviewed_at = None
            rejected_request.reviewed_by = None
            rejected_request.save()
            join_request = rejected_request
        else:
            # Create new request
            join_request = ClassroomJoinRequest.objects.create(
                classroom=classroom,
                student=user,
                message=message
            )
        
        return Response({
            "message": "Đã gửi yêu cầu tham gia lớp. Vui lòng chờ giáo viên phê duyệt.",
            "request_id": join_request.id,
            "classroom": {
                "id": classroom.id,
                "name": classroom.name,
                "teacher": classroom.teacher.full_name or classroom.teacher.email
            }
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="pending_requests")
    def pending_requests(self, request, pk=None):
        """Get pending join requests for a classroom (teacher only)."""
        from .models import ClassroomJoinRequest
        from .serializers import ClassroomJoinRequestSerializer
        
        classroom = self.get_object()
        
        # Only teacher can view
        if request.user != classroom.teacher:
            return Response({"error": "Chỉ giáo viên mới có quyền xem"}, status=status.HTTP_403_FORBIDDEN)
        
        requests = ClassroomJoinRequest.objects.filter(classroom=classroom, status="PENDING")
        serializer = ClassroomJoinRequestSerializer(requests, many=True)
        
        return Response({
            "count": requests.count(),
            "requests": serializer.data
        })

    @action(detail=True, methods=["post"], url_path="approve_student")
    def approve_student(self, request, pk=None):
        """Approve a student's join request."""
        from .models import ClassroomJoinRequest
        
        classroom = self.get_object()
        
        # Only teacher can approve
        if request.user != classroom.teacher:
            return Response({"error": "Chỉ giáo viên mới có quyền duyệt"}, status=status.HTTP_403_FORBIDDEN)
        
        request_id = request.data.get("request_id")
        if not request_id:
            return Response({"error": "request_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            join_request = ClassroomJoinRequest.objects.get(
                id=request_id, classroom=classroom, status="PENDING"
            )
        except ClassroomJoinRequest.DoesNotExist:
            return Response({"error": "Không tìm thấy yêu cầu"}, status=status.HTTP_404_NOT_FOUND)
        
        # Approve and add student to class
        join_request.approve(request.user)
        
        return Response({
            "message": f"Đã duyệt {join_request.student.full_name or join_request.student.email}",
            "student_id": join_request.student.id
        })

    @action(detail=True, methods=["post"], url_path="reject_student")
    def reject_student(self, request, pk=None):
        """Reject a student's join request."""
        from .models import ClassroomJoinRequest
        
        classroom = self.get_object()
        
        # Only teacher can reject
        if request.user != classroom.teacher:
            return Response({"error": "Chỉ giáo viên mới có quyền từ chối"}, status=status.HTTP_403_FORBIDDEN)
        
        request_id = request.data.get("request_id")
        if not request_id:
            return Response({"error": "request_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            join_request = ClassroomJoinRequest.objects.get(
                id=request_id, classroom=classroom, status="PENDING"
            )
        except ClassroomJoinRequest.DoesNotExist:
            return Response({"error": "Không tìm thấy yêu cầu"}, status=status.HTTP_404_NOT_FOUND)
        
        # Reject request
        join_request.reject(request.user)
        
        return Response({
            "message": f"Đã từ chối {join_request.student.full_name or join_request.student.email}"
        })

    @action(detail=True, methods=["post"], url_path="leave")
    def leave_class(self, request, pk=None):
        """Student leaves a class."""
        user = request.user
        
        # Only students can leave
        if user.role != "student":
            return Response({"error": "Only students can leave classes"}, status=status.HTTP_403_FORBIDDEN)
        
        classroom = self.get_object()
        
        # Check if student is in class
        if user not in classroom.students.all():
            return Response({"error": "Bạn không ở trong lớp này"}, status=status.HTTP_400_BAD_REQUEST)
        
        classroom.students.remove(user)
        
        return Response({"message": "Đã rời khỏi lớp"}, status=status.HTTP_200_OK)


    @action(detail=True, methods=["get"], url_path="leaderboard")
    def leaderboard(self, request, pk=None):
        """Get class leaderboard by cards learned (optimized with annotate)."""
        classroom = self.get_object()
        decks = classroom.decks.all()
        
        # Calculate total in 1 query using annotate
        leaderboard_data = classroom.students.annotate(
            total_cards=Sum(
                'progress__cards_learned', 
                filter=Q(progress__deck__in=decks)
            )
        ).order_by('-total_cards').values('id', 'full_name', 'email', 'total_cards')

        # Format data and add rank
        response_data = [
            {
                "student_id": item['id'],
                "name": item['full_name'] or item['email'],
                "cards_learned": item['total_cards'] or 0,
                "rank": index + 1
            }
            for index, item in enumerate(leaderboard_data)
        ]
        
        return Response(response_data)

    @action(detail=True, methods=["get"], url_path="my-progress")
    def my_progress(self, request, pk=None):
        """Get current user's progress in this class."""
        classroom = self.get_object()
        user = request.user
        
        progress_data = []
        for deck in classroom.decks.all():
            prog, _ = Progress.objects.get_or_create(student=user, deck=deck)
            total_cards = deck.card_count or 0
            cards_learned = prog.cards_learned or 0
            percent = round((cards_learned / total_cards * 100) if total_cards > 0 else 0, 1)
            
            progress_data.append({
                "deck_id": deck.id,
                "deck_title": deck.title,
                "cards_learned": cards_learned,
                "cards_to_review": prog.cards_to_review,
                "total_cards": total_cards,
                "percent": percent,
            })
        
        return Response(progress_data)


class DeckViewSet(viewsets.ModelViewSet):
    """API endpoint cho Deck (Anki decks)."""
    serializer_class = DeckSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == "teacher":
            return Deck.objects.filter(teacher=user)
        # Students có thể xem decks từ các lớp họ enrolled
        enrolled_classes = user.enrolled_classes.all()
        # Lấy Decks được gán trực tiếp vào Class HOẶC qua Test (backward compat)
        return Deck.objects.filter(
            Q(classrooms__in=enrolled_classes) |
            Q(tests__classroom__in=enrolled_classes)
        ).distinct()

    def perform_create(self, serializer):
        serializer.save(teacher=self.request.user)

    @action(detail=False, methods=["post"], url_path="upload", parser_classes=[MultiPartParser, FormParser])
    def upload(self, request):
        """Upload .apkg file directly and parse cards (Local storage)."""
        file_obj = request.FILES.get("file")
        title = request.data.get("title", "")  # Title is now optional

        if not file_obj:
            return Response(
                {"error": "File is required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Save to temp file first to extract deck name
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.apkg', delete=False) as tmp:
            tmp_path = tmp.name
            for chunk in file_obj.chunks():
                tmp.write(chunk)
        
        try:
            # Extract actual deck name from .apkg file FIRST
            actual_deck_name = get_primary_deck_name(tmp_path)
            
            # Use extracted name, fallback to user title, then filename
            final_title = actual_deck_name or title or file_obj.name.replace('.apkg', '')
            
            # Create Deck with correct name from the start
            deck = Deck.objects.create(
                teacher=request.user,
                title=final_title,
                card_count=0,
                status="DRAFT",
                appwrite_file_id="pending",
            )

            # Move temp file to permanent location
            decks_dir = os.path.join(settings.MEDIA_ROOT, 'decks')
            os.makedirs(decks_dir, exist_ok=True)
            
            apkg_filename = f"deck_{deck.id}.apkg"
            apkg_path = os.path.join(decks_dir, apkg_filename)
            
            import shutil
            shutil.move(tmp_path, apkg_path)
            tmp_path = None  # Mark as moved
            
            # Update deck with local file path
            deck.appwrite_file_id = f"local:{apkg_filename}"
            deck.save()

            # Parse cards
            parsed_cards = parse_anki_file(apkg_path)
            
            # Build warning if user-provided title was different
            deck_name_warning = None
            if title and actual_deck_name and title != actual_deck_name:
                deck_name_warning = f"Tên deck trong file là '{actual_deck_name}', đã sử dụng thay cho '{title}'"

            # Bulk create Card objects
            card_objects = [
                Card(
                    deck=deck,
                    front=c["front"],
                    back=c["back"],
                    note_id=c["note_id"],
                )
                for c in parsed_cards
            ]
            Card.objects.bulk_create(card_objects)

            # Update card count
            deck.card_count = len(card_objects)
            deck.save()

            # Prepare preview (first 5 cards)
            preview = [
                {"front": c.front[:200], "back": c.back[:200]}
                for c in card_objects[:5]
            ]

            response_data = {
                "deck": DeckSerializer(deck).data,
                "preview": preview,
                "actual_deck_name": actual_deck_name,
            }
            
            if deck_name_warning:
                response_data["warning"] = deck_name_warning
            
            return Response(response_data, status=status.HTTP_201_CREATED)

        except Exception as e:
            deck.delete()
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=["post"], url_path="create_from_id")
    def create_from_id(self, request):
        # Legacy method - kept for reference or backup
        pass

    @action(detail=True, methods=["post"], url_path="activate")
    def activate_deck(self, request, pk=None):
        """Kích hoạt deck sau khi giáo viên xác nhận preview."""
        deck = self.get_object()
        deck.status = "ACTIVE"
        deck.save()
        return Response({"message": "Deck activated", "deck": DeckSerializer(deck).data})

    def _get_file_url(self, file_id):
        """Get public/download URL for a file."""
        return f"{settings.APPWRITE_ENDPOINT}/storage/buckets/{settings.APPWRITE_BUCKET_ID}/files/{file_id}/view?project={settings.APPWRITE_PROJECT_ID}"

    def perform_destroy(self, instance):
        """Xóa file trên Appwrite khi xóa Deck."""
        if instance.appwrite_file_id:
            try:
                self._delete_from_appwrite(instance.appwrite_file_id)
            except Exception as e:
                # Log error but don't stop deletion
                print(f"Failed to delete Appwrite file: {e}")
        instance.delete()

    def _delete_from_appwrite(self, file_id):
        url = f"{settings.APPWRITE_ENDPOINT}/storage/buckets/{settings.APPWRITE_BUCKET_ID}/files/{file_id}"
        headers = {
            "X-Appwrite-Project": settings.APPWRITE_PROJECT_ID,
            "X-Appwrite-Key": settings.APPWRITE_API_KEY,
        }
        response = requests.delete(url, headers=headers)
        if response.status_code >= 400:
             print(f"Appwrite delete error: {response.text}")


class TestViewSet(viewsets.ModelViewSet):
    """API endpoint cho Test (bài kiểm tra)."""
    serializer_class = TestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == "teacher":
            return Test.objects.filter(teacher=user)
        # Students see tests from their enrolled classes
        return Test.objects.filter(classroom__students=user)

    def perform_create(self, serializer):
        serializer.save(teacher=self.request.user)
    
    @action(detail=True, methods=["get"])
    def stats(self, request, pk=None):
        """Thống kê kết quả bài kiểm tra."""
        test = self.get_object()
        
        # Check permission (only teacher)
        if request.user.role != "teacher" and test.teacher != request.user:
             return Response({"error": "Permission denied"}, status=status.HTTP_403_FORBIDDEN)
             
        submissions = test.submissions.all()
        total_students = test.classroom.students.count()
        submitted_count = submissions.count()
        
        avg_score = 0
        if submitted_count > 0:
            avg_score = sum(s.score for s in submissions) / submitted_count
            
        return Response({
            "total_students": total_students,
            "submitted_count": submitted_count,
            "avg_score": round(avg_score, 2),
            "submissions": [
                {
                    "student_name": s.student.full_name,
                    "email": s.student.email,
                    "score": s.score,
                    "submitted_at": s.submitted_at
                } for s in submissions
            ]
        })

    def destroy(self, request, *args, **kwargs):
        """Delete a test with proper error handling."""
        try:
            instance = self.get_object()
            # First delete related submissions to avoid FK issues
            instance.submissions.all().delete()
            instance.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            import traceback
            print(f"DELETE Test error: {e}")
            print(traceback.format_exc())
            return Response(
                {"error": f"Failed to delete test: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ProgressViewSet(viewsets.ModelViewSet):
    """API endpoint cho Progress (tiến độ học tập)."""
    serializer_class = ProgressSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Progress.objects.filter(student=self.request.user)

    def perform_create(self, serializer):
        serializer.save(student=self.request.user)


class SupportTicketViewSet(viewsets.ModelViewSet):
    """API endpoint cho Support Ticket."""
    serializer_class = SupportTicketSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        # Security: Only see own tickets
        return self.request.user.tickets.all().order_by("-created_at")

    def perform_create(self, serializer):
        # Security: Auto-assign user
        serializer.save(user=self.request.user)


# ============================================
# ANKI ADDON INTEGRATION ENDPOINTS
# ============================================

from django.http import FileResponse
from django.utils import timezone
from datetime import datetime
from .models import StudySession, CardReview
from .serializers import AnkiDeckSerializer, AnkiProgressSerializer


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def anki_my_decks(request):
    """
    GET /api/anki/my-decks/
    Trả về danh sách deck được giao cho học sinh này.
    Addon sẽ so sánh version để quyết định có cần download lại không.
    """
    user = request.user
    
    # Lấy tất cả decks từ các lớp học sinh đang tham gia
    enrolled_classes = user.enrolled_classes.all()
    decks = Deck.objects.filter(
        Q(classrooms__in=enrolled_classes) | 
        Q(tests__classroom__in=enrolled_classes),
        status="ACTIVE"
    ).distinct()
    
    serializer = AnkiDeckSerializer(decks, many=True)
    return Response(serializer.data)


from django.views.decorators.http import require_GET
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

@require_GET
def anki_deck_download(request, deck_id):
    """
    GET /api/anki/deck/{id}/download/
    Download file .apkg của deck.
    
    NOTE: This is a plain Django view (not DRF) to bypass content negotiation
    and allow Accept: application/octet-stream header for binary file download.
    """
    from django.http import HttpResponse, JsonResponse
    
    # Manual JWT authentication
    auth = JWTAuthentication()
    try:
        auth_result = auth.authenticate(request)
        if auth_result is None:
            return JsonResponse({"error": "Authentication required"}, status=401)
        user, token = auth_result
    except (InvalidToken, TokenError) as e:
        return JsonResponse({"error": f"Invalid token: {str(e)}"}, status=401)
    
    try:
        deck = Deck.objects.get(pk=deck_id, status="ACTIVE")
    except Deck.DoesNotExist:
        return JsonResponse({"error": "Deck không tồn tại"}, status=404)
    
    # Kiểm tra quyền: học sinh phải enrolled trong lớp có deck này
    # user already obtained from JWT auth above
    user_classes = user.enrolled_classes.all() if user.role == "student" else []
    deck_classes = deck.classrooms.all()
    
    # Teacher có thể download deck của mình
    if user.role == "teacher" and deck.teacher == user:
        pass  # OK
    elif user.role == "student" and deck_classes.filter(pk__in=[c.pk for c in user_classes]).exists():
        pass  # OK
    else:
        return JsonResponse({"error": "Không có quyền truy cập deck này"}, status=403)
    
    # Download từ Appwrite hoặc local và stream về client
    if not deck.appwrite_file_id or deck.appwrite_file_id == "local_upload":
        return JsonResponse({"error": "Deck chưa có file"}, status=404)
    
    try:
        import tempfile
        import os
        import logging
        from django.http import HttpResponse
        from django.conf import settings as django_settings
        
        logger = logging.getLogger(__name__)
        file_id = deck.appwrite_file_id
        
        # Check if it's a local file (format: "local:filename.apkg")
        if file_id.startswith("local:"):
            # Local file - read from media/decks/
            filename = file_id.replace("local:", "")
            local_path = os.path.join(django_settings.MEDIA_ROOT, "decks", filename)
            
            if not os.path.exists(local_path):
                return Response({"error": f"File không tồn tại: {filename}"}, status=status.HTTP_404_NOT_FOUND)
            
            file_size = os.path.getsize(local_path)
            logger.info(f"Serving local file: {local_path} ({file_size} bytes)")
            
            with open(local_path, 'rb') as f:
                file_content = f.read()
        else:
            # Appwrite file - download to temp file
            with tempfile.NamedTemporaryFile(suffix='.apkg', delete=False) as tmp_file:
                tmp_path = tmp_file.name
            
            download_from_appwrite(file_id, tmp_path)
            
            file_size = os.path.getsize(tmp_path)
            logger.info(f"Downloaded from Appwrite: {tmp_path} ({file_size} bytes)")
            
            # Read and stream response
            with open(tmp_path, 'rb') as f:
                file_content = f.read()
            
            # Cleanup temp file
            os.unlink(tmp_path)
        
        # Verify file is valid APKG (starts with PK - ZIP signature)
        if len(file_content) < 4 or file_content[:2] != b'PK':
            logger.error(f"Invalid APKG file! Size: {len(file_content)}, Header: {file_content[:20]}")
            return JsonResponse({"error": "File APKG không hợp lệ"}, status=500)
        
        logger.info(f"Sending deck {deck.title}: {len(file_content)} bytes")
        
        # Stream response with explicit Content-Length
        response = HttpResponse(file_content, content_type='application/octet-stream')
        response['Content-Disposition'] = f'attachment; filename="{deck.title}.apkg"'
        response['Content-Length'] = str(len(file_content))
        # Add lms_deck_id header for addon to read
        response['X-LMS-Deck-ID'] = str(deck.id)
        response['X-LMS-Deck-Version'] = str(deck.version)
        return response
        
    except Exception as e:
        import traceback
        logging.error(f"Download error: {traceback.format_exc()}")
        return JsonResponse({"error": f"Lỗi download: {str(e)}"}, status=500)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def anki_progress(request):
    """
    POST /api/anki/progress/
    Nhận tiến độ học tập từ Addon (Batch Processing).
    Addon gửi lên mảng reviews thay vì từng cái một để tránh DDOS.
    """
    serializer = AnkiProgressSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    data = serializer.validated_data
    deck_id = data['lms_deck_id']
    reviews_data = data['reviews']
    
    if not reviews_data:
        return Response({"status": "empty", "synced_count": 0})
    
    try:
        deck = Deck.objects.get(pk=deck_id)
    except Deck.DoesNotExist:
        return Response({"error": "Deck không tồn tại"}, status=status.HTTP_404_NOT_FOUND)
    
    # Tính toán thời gian và duration từ reviews
    timestamps = [r['timestamp'] for r in reviews_data]
    start_time = datetime.fromtimestamp(min(timestamps), tz=timezone.utc)
    total_time_ms = sum(r['time'] for r in reviews_data)
    
    # 1. Tạo StudySession
    session = StudySession.objects.create(
        student=request.user,
        deck=deck,
        start_time=start_time,
        duration_seconds=total_time_ms // 1000,
        cards_reviewed=len(reviews_data)
    )
    
    # 2. Bulk Create CardReviews (Siêu nhanh, không DDOS DB)
    review_objects = [
        CardReview(
            session=session,
            card_id=r['card_id'],
            ease=r['ease'],
            time_taken=r['time'],
            reviewed_at=datetime.fromtimestamp(r['timestamp'], tz=timezone.utc)
        ) for r in reviews_data
    ]
    CardReview.objects.bulk_create(review_objects)
    
    # 3. Update Progress tổng hợp
    progress, _ = Progress.objects.get_or_create(student=request.user, deck=deck)
    progress.cards_learned = CardReview.objects.filter(
        session__student=request.user,
        session__deck=deck,
        ease__gte=3  # Good or Easy
    ).values('card_id').distinct().count()
    progress.save()
    
    # 4. Update DailyStudyStats for today
    from .models import DailyStudyStats, StudentStreak
    today = timezone.now().date()
    
    daily_stats, created = DailyStudyStats.objects.get_or_create(
        student=request.user,
        date=today,
        defaults={
            'cards_reviewed': 0,
            'time_spent_seconds': 0,
            'cards_learned': 0,
            'retention_rate': 0,
        }
    )
    
    # Aggregate today's stats from CardReview
    daily_stats.cards_reviewed += len(reviews_data)
    daily_stats.time_spent_seconds += total_time_ms // 1000
    
    # Count new cards (first time seen today with ease >= 3)
    good_easy_count = sum(1 for r in reviews_data if r['ease'] >= 3)
    again_count = sum(1 for r in reviews_data if r['ease'] == 1)
    
    daily_stats.cards_learned += good_easy_count
    
    # Calculate retention rate (% not marked Again)
    if len(reviews_data) > 0:
        new_retention = (len(reviews_data) - again_count) / len(reviews_data)
        # Weighted average with existing
        if daily_stats.cards_reviewed > len(reviews_data):
            old_weight = (daily_stats.cards_reviewed - len(reviews_data)) / daily_stats.cards_reviewed
            new_weight = len(reviews_data) / daily_stats.cards_reviewed
            daily_stats.retention_rate = (daily_stats.retention_rate * old_weight) + (new_retention * new_weight)
        else:
            daily_stats.retention_rate = new_retention
    
    daily_stats.save()
    
    # 5. Update StudentStreak
    streak, _ = StudentStreak.objects.get_or_create(student=request.user)
    streak.update_streak(today)
    
    return Response({
        "status": "synced",
        "synced_count": len(review_objects),
        "session_id": session.id
    })


@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def anki_token_exchange(request):
    """
    POST /api/anki/token-exchange/
    
    Exchange Anki sync email for JWT tokens.
    Since user is already authenticated with Anki sync server (same credentials),
    we can issue JWT tokens directly based on email.
    
    Security: Uses a shared secret between addon and server.
    """
    from rest_framework_simplejwt.tokens import RefreshToken
    from django.conf import settings
    import hmac
    import hashlib
    
    email = request.data.get("email")
    timestamp = request.data.get("timestamp")
    signature = request.data.get("signature")
    
    if not email or not timestamp or not signature:
        return Response(
            {"error": "Missing required fields"}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Verify signature using shared secret
    # Secret should be set in settings.py: ANKI_ADDON_SECRET = "your-secret-key"
    secret = getattr(settings, 'ANKI_ADDON_SECRET', 'default-secret-change-me')
    
    # Create expected signature: HMAC-SHA256(secret, email:timestamp)
    message = f"{email}:{timestamp}"
    expected_signature = hmac.new(
        secret.encode(), 
        message.encode(), 
        hashlib.sha256
    ).hexdigest()
    
    if not hmac.compare_digest(signature, expected_signature):
        return Response(
            {"error": "Invalid signature"}, 
            status=status.HTTP_403_FORBIDDEN
        )
    
    # Check timestamp is not too old (5 minutes)
    import time
    try:
        ts = int(timestamp)
        if abs(time.time() - ts) > 300:
            return Response(
                {"error": "Timestamp expired"}, 
                status=status.HTTP_403_FORBIDDEN
            )
    except ValueError:
        return Response(
            {"error": "Invalid timestamp"}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Find user by email
    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response(
            {"error": "User not found"}, 
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Generate JWT tokens
    refresh = RefreshToken.for_user(user)
    
    return Response({
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": getattr(user, 'full_name', user.email),
            "role": getattr(user, 'role', 'student'),
        }
    })


# ============================================
# ANKI SYNC SERVER ANALYTICS ENDPOINTS
# ============================================

@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def my_anki_stats(request):
    """
    GET /api/anki/stats/
    Get current user's Anki learning statistics from sync server.
    
    Triggers a sync from user's Anki collection to Django DB,
    then returns aggregated metrics.
    """
    from .services.anki_analytics import AnkiAnalyticsService
    
    service = AnkiAnalyticsService(request.user)
    
    # Trigger sync first (reads from collection.anki2)
    try:
        new_entries = service.sync_revlog()
    except Exception as e:
        new_entries = 0
        # Log but don't fail - user may not have synced yet
        import logging
        logging.warning(f"Failed to sync revlog for {request.user.email}: {e}")
    
    # Get metrics
    metrics = service.get_metrics()
    metrics['new_entries_synced'] = new_entries
    
    return Response(metrics)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def class_anki_stats(request, class_id):
    """
    GET /api/anki/class/{class_id}/stats/
    Get Anki stats for all students in a class (teacher only).
    
    Returns aggregated metrics for each student in the class.
    """
    from .services.anki_analytics import AnkiAnalyticsService
    
    # Verify teacher owns this class
    try:
        classroom = Classroom.objects.get(id=class_id, teacher=request.user)
    except Classroom.DoesNotExist:
        return Response(
            {"error": "Classroom not found or you don't have permission"},
            status=status.HTTP_404_NOT_FOUND
        )
    
    students_stats = []
    for student in classroom.students.all():
        service = AnkiAnalyticsService(student)
        
        # Sync each student's revlog
        try:
            service.sync_revlog()
        except Exception:
            pass  # Continue even if sync fails
        
        metrics = service.get_metrics()
        students_stats.append({
            "student_id": student.id,
            "student_name": student.full_name or student.email,
            "email": student.email,
            "metrics": metrics
        })
    
    # Sort by cards reviewed (most active first)
    students_stats.sort(
        key=lambda x: x['metrics']['month']['cards_reviewed'],
        reverse=True
    )
    
    return Response({
        "classroom": {
            "id": classroom.id,
            "name": classroom.name,
        },
        "student_count": len(students_stats),
        "students": students_stats
    })


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def anki_calendar(request):
    """
    GET /api/anki/calendar/?days=30
    Get study activity for calendar heatmap display.
    
    Query params:
        days: Number of days to look back (default: 30, max: 365)
    """
    from .services.anki_analytics import AnkiAnalyticsService
    
    days = min(int(request.query_params.get("days", 30)), 365)
    
    service = AnkiAnalyticsService(request.user)
    
    # Sync first
    try:
        service.sync_revlog()
    except Exception:
        pass
    
    calendar_data = service.get_study_calendar(days=days)
    
    return Response({
        "days": days,
        "activity": calendar_data
    })


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def anki_sync_status(request):
    """
    GET /api/anki/sync-status/
    Check if user has synced with Anki sync server.
    
    Returns sync server info and user's sync status.
    """
    from .anki_sync import get_user_collection_path, user_has_synced
    
    collection_path = get_user_collection_path(request.user.email)
    has_synced = user_has_synced(request.user.email)
    
    # Get last sync time from collection file
    last_sync = None
    if has_synced:
        import os
        try:
            mtime = os.path.getmtime(str(collection_path))
            last_sync = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
        except Exception:
            pass
    
    return Response({
        "email": request.user.email,
        "has_synced": has_synced,
        "last_sync": last_sync,
        "sync_server_url": "https://sync.ankivn.com",
        "instructions": {
            "desktop": "Anki → Tools → Preferences → Syncing → Self-hosted sync server",
            "android": "AnkiDroid → Settings → Advanced → Custom sync server",
        } if not has_synced else None
    })


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def sync_pending_decks(request):
    """
    POST /api/anki/sync-pending-decks/
    
    Inject any pending decks that were assigned to student's classes
    while they hadn't synced yet. Call this after first sync.
    
    This handles the case where:
    1. Teacher assigns deck to class
    2. Student hasn't synced yet (no collection)
    3. Student syncs for first time (collection created)
    4. Student calls this endpoint to get any missed decks
    """
    from .anki_sync import user_has_synced
    from .services.deck_injector import inject_deck_to_student
    from .utils import download_from_appwrite
    
    user = request.user
    
    if not user_has_synced(user.email):
        return Response({
            "error": "You must sync with Anki at least once first",
            "has_synced": False
        }, status=status.HTTP_400_BAD_REQUEST)
    
    # Find all classes the student is in
    classrooms = Classroom.objects.filter(students=user)
    
    results = {"injected": [], "failed": [], "skipped": []}
    
    for classroom in classrooms:
        for deck in classroom.decks.all():
            if not deck.appwrite_file_id or deck.appwrite_file_id in ['pending', 'local_upload']:
                results["skipped"].append({"deck": deck.title, "reason": "No file"})
                continue
            
            try:
                from django.conf import settings
                import os
                
                # Handle local files (format: local:filename.apkg)
                if deck.appwrite_file_id.startswith('local:'):
                    filename = deck.appwrite_file_id.replace('local:', '')
                    local_path = os.path.join(settings.MEDIA_ROOT, 'decks', filename)
                    
                    if not os.path.exists(local_path):
                        results["failed"].append({"deck": deck.title, "error": "File not found"})
                        continue
                    
                    with open(local_path, 'rb') as f:
                        deck_content = f.read()
                else:
                    # Download from Appwrite
                    import tempfile
                    
                    with tempfile.NamedTemporaryFile(suffix='.apkg', delete=False) as tmp:
                        tmp_path = tmp.name
                    
                    download_from_appwrite(deck.appwrite_file_id, tmp_path)
                    
                    with open(tmp_path, 'rb') as f:
                        deck_content = f.read()
                    
                    os.unlink(tmp_path)
                
                # Inject deck
                success, message = inject_deck_to_student(user.email, deck_content)
                
                if success:
                    results["injected"].append({
                        "deck": deck.title,
                        "classroom": classroom.name
                    })
                else:
                    results["failed"].append({
                        "deck": deck.title,
                        "error": message
                    })
            except Exception as e:
                results["failed"].append({
                    "deck": deck.title,
                    "error": str(e)
                })
    
    return Response({
        "message": f"Injected {len(results['injected'])} decks",
        "results": results,
        "note": "Sync with Anki again to see the new decks"
    })


# ============================================
# STUDENT ANALYTICS ENDPOINTS
# ============================================

@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def student_stats(request):
    """
    GET /api/student/stats/
    Return overview statistics for student dashboard.
    Uses aggregated tables for optimal performance.
    """
    from .services.student_analytics import StudentAnalyticsService
    
    service = StudentAnalyticsService(request.user)
    overview = service.get_overview_stats()
    today = service.get_today_stats()
    
    return Response({
        **overview,
        "today": today
    })


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def student_history(request):
    """
    GET /api/student/history/?days=30
    Return study history for charts.
    Dates are in ISO format (UTC) for frontend timezone conversion.
    """
    from .services.student_analytics import StudentAnalyticsService
    
    days = int(request.query_params.get('days', 30))
    days = min(days, 365)  # Cap at 1 year
    
    service = StudentAnalyticsService(request.user)
    history = service.get_study_history(days)
    deck_progress = service.get_deck_progress()
    
    return Response({
        "history": history,
        "deck_progress": deck_progress
    })


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def class_analytics(request, class_id):
    """
    GET /api/classes/{id}/analytics/
    Return analytics for a class (teachers only).
    """
    from .services.student_analytics import TeacherAnalyticsService
    
    try:
        classroom = Classroom.objects.get(pk=class_id)
    except Classroom.DoesNotExist:
        return Response({"error": "Class not found"}, status=404)
    
    # Check permission - only teacher or enrolled students can view
    user = request.user
    is_teacher = classroom.teacher == user
    is_student = classroom.students.filter(pk=user.pk).exists()
    
    if not is_teacher and not is_student:
        return Response({"error": "Permission denied"}, status=403)
    
    service = TeacherAnalyticsService(classroom)
    overview = service.get_class_overview()
    
    # Only teachers can see individual student progress
    if is_teacher:
        students = service.get_student_progress_list()
        overview["students"] = students
    
    return Response(overview)
