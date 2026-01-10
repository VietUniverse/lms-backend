from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.conf import settings
from .models import SupportTicket

@receiver(pre_save, sender=SupportTicket)
def capture_old_status(sender, instance, **kwargs):
    """Lưu trạng thái cũ trước khi save để so sánh."""
    if instance.pk:
        old_ticket = SupportTicket.objects.get(pk=instance.pk)
        instance._old_status = old_ticket.status
    else:
        instance._old_status = None

@receiver(post_save, sender=SupportTicket)
def send_status_change_email(sender, instance, created, **kwargs):
    """Gửi email khi trạng thái ticket thay đổi."""
    if created:
        # Email xác nhận đã nhận ticket
        subject = f"[LMS Support] Đã nhận yêu cầu hỗ trợ #{instance.pk}"
        message = f"""Chào {instance.user.full_name},

Chúng tôi đã nhận được yêu cầu hỗ trợ của bạn: "{instance.subject}".
Đội ngũ Admin sẽ xem xét và phản hồi sớm nhất.

Trân trọng,
Anki LMS Team
"""
        try:
             send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [instance.user.email],
                fail_silently=True,
            )
        except Exception as e:
            print(f"Failed to send email: {e}")

    elif hasattr(instance, '_old_status') and instance._old_status != instance.status:
        # Email thông báo đổi trạng thái
        status_display = dict(SupportTicket.STATUS_CHOICES).get(instance.status, instance.status)
        subject = f"[LMS Support] Cập nhật trạng thái ticket #{instance.pk}"
        message = f"""Chào {instance.user.full_name},

Yêu cầu hỗ trợ "{instance.subject}" của bạn đã được chuyển sang trạng thái: {status_display}.

Vui lòng kiểm tra Help Center để biết thêm chi tiết.

Trân trọng,
Anki LMS Team
"""
        try:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [instance.user.email],
                fail_silently=True,
            )
        except Exception as e:
            print(f"Failed to send email: {e}")
