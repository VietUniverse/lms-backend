# LMS Anki Addon

Addon tích hợp Anki Desktop với LMS, cho phép học sinh:
- Đăng nhập bằng tài khoản LMS
- Tự động tải deck được giáo viên giao
- Đồng bộ tiến độ học lên LMS

## Cài đặt

1. Download file `lms_addon.ankiaddon`
2. Mở Anki Desktop
3. Vào **Tools > Add-ons > Install from file...**
4. Chọn file `lms_addon.ankiaddon`
5. Khởi động lại Anki

## Sử dụng

### Đăng nhập
1. Vào **Tools > LMS > Đăng nhập**
2. Nhập LMS URL (hỏi giáo viên nếu chưa biết)
3. Nhập email và mật khẩu tài khoản LMS
4. Bấm **Đăng nhập**

### Tải Deck
- Vào **Tools > LMS > Đồng bộ LMS**
- Addon sẽ tự động tải các deck mới được giao
- Chỉ tải khi có phiên bản mới (tiết kiệm băng thông)

### Học và Đồng bộ Tiến độ
- Học bài như bình thường
- Tiến độ được cache tự động
- Đồng bộ lên LMS khi:
  - Bấm **Đồng bộ** trong Anki
  - Bấm **Tools > LMS > Đồng bộ LMS**
  - Đủ 50 reviews hoặc sau 10 phút

### Kiểm tra Trạng thái
- Vào **Tools > LMS > Cài đặt**
- Xem số reviews đang chờ
- Xem deck đang theo dõi

## Lưu ý

- Chỉ deck từ LMS mới được theo dõi tiến độ
- Deck tự tạo/tải từ nguồn khác không ảnh hưởng
- Token tự động refresh, không cần đăng nhập lại

## Troubleshooting

| Lỗi | Giải pháp |
|-----|-----------|
| Không kết nối được | Kiểm tra LMS URL, internet |
| Sai mật khẩu | Thử reset password trên web LMS |
| Deck không tải | Kiểm tra giáo viên đã giao deck chưa |
