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

    @action(detail=False, methods=["post"], url_path="upload")
    def upload_apkg(self, request):
        """
        Upload file .apkg lên Appwrite và tạo Deck record.
        Frontend gửi file qua multipart/form-data.
        """
        file = request.FILES.get("file")
        if not file:
            return Response({"error": "No file provided"}, status=status.HTTP_400_BAD_REQUEST)

        # Validate file extension
        if not file.name.endswith(".apkg"):
            return Response({"error": "Only .apkg files are allowed"}, status=status.HTTP_400_BAD_REQUEST)

        # Upload to Appwrite
        try:
            appwrite_response = self._upload_to_appwrite(file)
        except Exception as e:
            return Response({"error": f"Appwrite upload failed: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Create Deck record
        deck = Deck.objects.create(
            teacher=request.user,
            title=file.name.replace(".apkg", ""),
            appwrite_file_id=appwrite_response["$id"],
            appwrite_file_url=self._get_file_url(appwrite_response["$id"]),
            card_count=0,  # TODO: Parse .apkg to get actual count
        )

        return Response(DeckSerializer(deck).data, status=status.HTTP_201_CREATED)

    def _upload_to_appwrite(self, file):
        """Upload file to Appwrite Storage."""
        import uuid
        url = f"{settings.APPWRITE_ENDPOINT}/storage/buckets/{settings.APPWRITE_BUCKET_ID}/files"
        headers = {
            "X-Appwrite-Project": settings.APPWRITE_PROJECT_ID,
            "X-Appwrite-Key": settings.APPWRITE_API_KEY,
        }
        file_id = str(uuid.uuid4())
        files = {"file": (file.name, file.read(), file.content_type or "application/octet-stream")}
        data = {"fileId": file_id}

        response = requests.post(url, headers=headers, files=files, data=data)
        response.raise_for_status()
        return response.json()

    def _get_file_url(self, file_id):
        """Get public/download URL for a file."""
        return f"{settings.APPWRITE_ENDPOINT}/storage/buckets/{settings.APPWRITE_BUCKET_ID}/files/{file_id}/view?project={settings.APPWRITE_PROJECT_ID}"


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
