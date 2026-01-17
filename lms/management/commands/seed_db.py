from django.core.management.base import BaseCommand
from accounts.models import User
from lms.models import Classroom, Deck
from django.db import IntegrityError

class Command(BaseCommand):
    help = 'Seeds database with test data (Admin, Student, Class, Deck)'

    def handle(self, *args, **options):
        self.stdout.write('🌱 Seeding database...')

        # 1. Superuser
        try:
            admin = User.objects.get(username='admin@root.com')
            admin.email = 'admin@root.com'
            admin.set_password('password123')
            admin.save()
            self.stdout.write(self.style.SUCCESS('✅ Found/Updated Admin: admin@root.com'))
        except User.DoesNotExist:
            User.objects.create_superuser(username='admin@root.com', email='admin@root.com', password='password123')
            self.stdout.write(self.style.SUCCESS('✅ Created Admin: admin@root.com'))
        
        # 2. Student
        try:
            student = User.objects.get(username='sinhvien1@test.com')
            student.email = 'sinhvien1@test.com'
            student.set_password('password123')
            student.full_name = "Nguyen Van A"
            student.role = 'student'
            student.save()
            self.stdout.write(self.style.SUCCESS('✅ Found/Updated Student: sinhvien1@test.com'))
        except User.DoesNotExist:
            student = User.objects.create_user(username='sinhvien1@test.com', email='sinhvien1@test.com', password='password123')
            student.full_name = "Nguyen Van A"
            student.role = 'student'
            student.save()
            self.stdout.write(self.style.SUCCESS('✅ Created Student: sinhvien1@test.com'))

        # 3. Class (Teacher is Admin)
        admin = User.objects.get(username='admin@root.com')
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
        else:
            self.stdout.write(f'   Class {classroom.name} already exists')
        
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
        else:
             self.stdout.write(f'   Deck {deck.title} already exists')

        self.stdout.write(self.style.SUCCESS('🎉 Database seeded successfully!'))
