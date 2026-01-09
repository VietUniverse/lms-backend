from django.http import JsonResponse
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.conf import settings
from django.contrib.auth import get_user_model
import requests

from .models import Classroom, Deck, Assignment, Progress
from .serializers import (
    ClassroomSerializer,
    ClassroomDetailSerializer,
    DeckSerializer,
    AssignmentSerializer,
    ProgressSerializer,
)

User = get_user_model()


def index(request):
    return JsonResponse({"status": "ok", "message": "LMS API is running"})


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
        return Deck.objects.filter(assignments__classroom__in=enrolled_classes).distinct()

    def perform_create(self, serializer):
        serializer.save(teacher=self.request.user)

    @action(detail=False, methods=["post"], url_path="create_from_id")
    def create_from_id(self, request):
        """
        Tạo Deck record từ Appwrite File ID (đã upload từ frontend).
        """
        file_id = request.data.get("file_id")
        title = request.data.get("title")
        file_name = request.data.get("file_name", "unknown.apkg")

        if not file_id or not title:
            return Response({"error": "Missing file_id or title"}, status=status.HTTP_400_BAD_REQUEST)

        # Create Deck record
        deck = Deck.objects.create(
            teacher=request.user,
            title=title,
            appwrite_file_id=file_id,
            appwrite_file_url=self._get_file_url(file_id),
            card_count=0,
        )

        return Response(DeckSerializer(deck).data, status=status.HTTP_201_CREATED)

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


class AssignmentViewSet(viewsets.ModelViewSet):
    """API endpoint cho Assignment (bài tập/kiểm tra)."""
    serializer_class = AssignmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == "teacher":
            return Assignment.objects.filter(teacher=user)
        # Students see assignments from their enrolled classes
        return Assignment.objects.filter(classroom__students=user)

    def perform_create(self, serializer):
        serializer.save(teacher=self.request.user)


class ProgressViewSet(viewsets.ModelViewSet):
    """API endpoint cho Progress (tiến độ học tập)."""
    serializer_class = ProgressSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Progress.objects.filter(student=self.request.user)

    def perform_create(self, serializer):
        serializer.save(student=self.request.user)
