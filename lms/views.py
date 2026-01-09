from django.http import JsonResponse
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action, api_view, permission_classes
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
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
    ProgressSerializer,
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
            models.Q(classrooms__in=enrolled_classes) |
            models.Q(tests__classroom__in=enrolled_classes)
        ).distinct()

    def perform_create(self, serializer):
        serializer.save(teacher=self.request.user)

    @action(detail=False, methods=["post"], url_path="create_from_id")
    def create_from_id(self, request):
        """
        Tạo Deck record từ Appwrite File ID (đã upload từ frontend).
        Parse file .apkg để lấy thẻ và trả về preview.
        """
        file_id = request.data.get("file_id")
        title = request.data.get("title")

        if not file_id or not title:
            return Response({"error": "Missing file_id or title"}, status=status.HTTP_400_BAD_REQUEST)

        # Create Deck record with DRAFT status
        deck = Deck.objects.create(
            teacher=request.user,
            title=title,
            appwrite_file_id=file_id,
            appwrite_file_url=self._get_file_url(file_id),
            card_count=0,
            status="DRAFT",
        )

        # Download and parse the Anki file
        temp_file = None
        try:
            temp_file = tempfile.NamedTemporaryFile(suffix=".apkg", delete=False)
            temp_file.close()
            download_from_appwrite(file_id, temp_file.name)
            parsed_cards = parse_anki_file(temp_file.name)

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
            # Cleanup deck if parsing failed
            deck.delete()
            return Response({"error": f"Failed to parse Anki file: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        finally:
            # Cleanup temp file
            if temp_file and os.path.exists(temp_file.name):
                os.unlink(temp_file.name)

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
