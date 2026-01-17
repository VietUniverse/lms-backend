from django.core.management.base import BaseCommand
from accounts.models import User
from lms.models import Classroom, Deck
from django.utils import timezone

class Command(BaseCommand):
    help = 'Seeds database with test data (Admin, Student, Class, Deck)'

    def handle(self, *args, **options):
        self.stdout.write('🌱 Seeding database...')

        # 1. Superuser
        if not User.objects.filter(email='admin@root.com').exists():
            User.objects.create_superuser('admin@root.com', 'password123')
            self.stdout.write(self.style.SUCCESS('✅ Created Admin: admin@root.com / password123'))
        
        # 2. Student
        student, created = User.objects.get_or_create(email='sinhvien1@test.com')
        if created:
            student.set_password('password123')
            student.full_name = "Nguyen Van A"
            student.role = 'student'
            student.save()
            self.stdout.write(self.style.SUCCESS('✅ Created Student: sinhvien1@test.com / password123'))

        # 3. Class (Teacher is Admin)
        admin = User.objects.get(email='admin@root.com')
        classroom, created = Classroom.objects.get_or_create(
            name='IELTS Intensity',
            defaults={
                'description': 'Lớp học IELTS cấp tốc', 
                'join_code': 'IELTS101',
                'teacher': admin,
                'status': 'ACTIVE'
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'✅ Created Class: {classroom.name}'))
        
        # Add student to class
        if student not in classroom.students.all():
            classroom.students.add(student)
            self.stdout.write(self.style.SUCCESS(f'   -> Added sinhvien1 to class'))

        # 4. Deck
        deck, created = Deck.objects.get_or_create(
            title='Collocations',
            defaults={
                'description': '200 Collocations thông dụng',
                'classroom': classroom
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f'✅ Created Deck: {deck.title}'))

        self.stdout.write(self.style.SUCCESS('🎉 Database seeded successfully!'))
