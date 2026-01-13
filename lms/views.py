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
from .utils import download_from_appwrite, parse_anki_file
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
        """Thêm deck vào lớp."""
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
        return Response({"message": "Deck added to class"}, status=status.HTTP_200_OK)

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
        """Student joins a class using join code."""
        from django.db import transaction
        
        user = request.user
        
        # Only students can join
        if user.role != "student":
            return Response({"error": "Only students can join classes"}, status=status.HTTP_403_FORBIDDEN)
        
        code = request.data.get("code", "").upper()
        
        if not code:
            return Response({"error": "Code is required"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            classroom = Classroom.objects.get(join_code=code, status="ACTIVE")
        except Classroom.DoesNotExist:
            return Response({"error": "Không tìm thấy lớp học với mã này"}, status=status.HTTP_404_NOT_FOUND)
        
        # Check if already joined
        if user in classroom.students.all():
            return Response({"error": "Bạn đã tham gia lớp này rồi"}, status=status.HTTP_400_BAD_REQUEST)
        
        # Add student with atomic transaction
        with transaction.atomic():
            classroom.students.add(user)
        
        return Response({
            "message": "Tham gia lớp thành công",
            "classroom": {
                "id": classroom.id,
                "name": classroom.name,
            }
        }, status=status.HTTP_200_OK)

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
        """Upload .apkg file directly and parse cards (Bypassing Appwrite)."""
        file_obj = request.FILES.get("file")
        title = request.data.get("title")

        if not file_obj or not title:
            return Response(
                {"error": "File and title are required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create Deck
        deck = Deck.objects.create(
            teacher=request.user,
            title=title,
            card_count=0,
            status="DRAFT",
            appwrite_file_id="local_upload", # Placeholder
        )

        try:
            # Save uploaded file to temp
            with tempfile.NamedTemporaryFile(suffix=".apkg", delete=False) as temp_file:
                for chunk in file_obj.chunks():
                    temp_file.write(chunk)
                temp_path = temp_file.name

            # Parse
            parsed_cards = parse_anki_file(temp_path)

            # Cleanup temp file
            os.unlink(temp_path)

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

            return Response({
                "deck": DeckSerializer(deck).data,
                "preview": preview,
            }, status=status.HTTP_201_CREATED)

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


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def anki_deck_download(request, deck_id):
    """
    GET /api/anki/deck/{id}/download/
    Download file .apkg của deck.
    Sử dụng FileResponse để stream file, tránh load cả file vào RAM.
    """
    try:
        deck = Deck.objects.get(pk=deck_id, status="ACTIVE")
    except Deck.DoesNotExist:
        return Response({"error": "Deck không tồn tại"}, status=status.HTTP_404_NOT_FOUND)
    
    # Kiểm tra quyền: học sinh phải enrolled trong lớp có deck này
    user = request.user
    user_classes = user.enrolled_classes.all() if user.role == "student" else []
    deck_classes = deck.classrooms.all()
    
    # Teacher có thể download deck của mình
    if user.role == "teacher" and deck.teacher == user:
        pass  # OK
    elif user.role == "student" and deck_classes.filter(pk__in=[c.pk for c in user_classes]).exists():
        pass  # OK
    else:
        return Response({"error": "Không có quyền truy cập deck này"}, status=status.HTTP_403_FORBIDDEN)
    
    # Download từ Appwrite và stream về client
    if not deck.appwrite_file_id or deck.appwrite_file_id == "local_upload":
        return Response({"error": "Deck chưa có file"}, status=status.HTTP_404_NOT_FOUND)
    
    try:
        # Download từ Appwrite
        file_content = download_from_appwrite(deck.appwrite_file_id)
        
        # Stream response
        from django.http import HttpResponse
        response = HttpResponse(file_content, content_type='application/octet-stream')
        response['Content-Disposition'] = f'attachment; filename="{deck.title}.apkg"'
        # Add lms_deck_id header for addon to read
        response['X-LMS-Deck-ID'] = str(deck.id)
        response['X-LMS-Deck-Version'] = str(deck.version)
        return response
        
    except Exception as e:
        return Response({"error": f"Lỗi download: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
    
    return Response({
        "status": "synced",
        "synced_count": len(review_objects),
        "session_id": session.id
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
        "sync_server_url": "http://localhost:8080",  # TODO: Make configurable
        "instructions": {
            "desktop": "Anki → Tools → Preferences → Syncing → Self-hosted sync server",
            "android": "AnkiDroid → Settings → Advanced → Custom sync server",
        } if not has_synced else None
    })
