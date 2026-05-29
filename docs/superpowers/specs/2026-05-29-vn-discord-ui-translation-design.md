# Vietnamese Discord UI Translation Design

## Goal

Khi guild cấu hình ngôn ngữ là `VN`, toàn bộ text người dùng nhìn thấy trên Discord phải nhất quán tiếng Việt. Không dịch tên slash command, prefix command, hay khóa option kỹ thuật.

## Scope

- Dịch message, embed, button, modal, select placeholder, view title, description, và error text phục vụ Discord UI.
- Chuẩn hóa `langs/VN.json` cho các key runtime còn thiếu hoặc còn tiếng Anh.
- Bổ sung các key runtime mới cho help/debug/inbox/embed-builder/pagination/playlist UI đang hardcode tiếng Anh.
- Cập nhật `local_langs/vi.json` chỉ ở phần mô tả và label người dùng nhìn thấy; giữ nguyên command names và option keys hiện có.
- Đổi link GitHub hiển thị trên Discord UI từ upstream sang fork `https://github.com/LouisKien/Vocard`.

## Non-Goals

- Không dịch tài liệu repo, code comments, log nội bộ, hay README.
- Không đổi tên command `/play`, `/playlist`, prefix commands, hay internal config keys.
- Không cố dịch mọi locale khác ngoài việc giữ chúng không bị gãy.

## Design Decisions

### 1. Key-level fallback sang EN

Các view Discord hiện có nhiều text hardcode. Nếu chỉ thêm key mới cho `VN` thì các locale khác sẽ trả về `Not found!`. Vì vậy `LangHandler._get_lang()` sẽ fallback theo thứ tự:

1. locale đang dùng
2. `EN`
3. default locale
4. `Not found!`

Điều này giữ an toàn cho các locale khác khi chỉ thêm key mới cho `EN` và `VN`.

### 2. Không hardcode tiếng Việt vào view chung

Những view đang hardcode tiếng Anh sẽ chuyển sang đọc từ `langs/*.json`, thay vì đổi trực tiếp sang tiếng Việt trong Python. Mục tiêu là:

- `VN` hiển thị tiếng Việt
- locale khác vẫn hiển thị tiếng Anh fallback

### 3. Giữ nguyên command identity

`local_langs/vi.json` chỉ sửa mô tả và nhãn hiển thị. Các tên lệnh và khóa slash option đang dùng để sync command sẽ không đổi để tránh breaking Discord command registration.

## Files Expected To Change

- `langs/EN.json`
- `langs/VN.json`
- `local_langs/vi.json`
- `voicelink/language.py`
- `voicelink/views/help.py`
- `voicelink/views/pagination.py`
- `voicelink/views/embed_builder.py`
- `voicelink/views/inbox.py`
- `voicelink/views/playlist.py`
- `voicelink/views/debug.py`
- `cogs/settings.py`
- `tests/test_vietnamese_ui_translation.py`

## Verification

- New tests prove VN UI text is present for the translated components.
- New tests prove new runtime keys fall back to EN for non-VN locales.
- New tests prove Discord help UI points to `LouisKien/Vocard`.
- Full test suite still passes.
