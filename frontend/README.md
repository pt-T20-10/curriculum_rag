# Curriculum RAG Frontend

Frontend React/Vite cho hệ thống AI Textbook Generator. Giao diện hỗ trợ đầy đủ tiếng Việt và tiếng Anh, bao gồm public/auth pages, quy trình tạo giáo trình, dashboard, tài khoản, nạp credit và các trang quản trị.

## Main Features

- Chuyển ngôn ngữ UI giữa `vi` và `en`; lựa chọn được lưu qua reload.
- Đăng ký, đăng nhập local/Google OAuth, quên và đặt lại mật khẩu.
- Tạo giáo trình theo workflow hai phase: planning review rồi content generation.
- Chỉnh curriculum trước khi xác nhận: thêm/xóa chapter và subsection, sửa title.
- Theo dõi realtime phase, chapter, subsection, sub-stage và nội dung preview.
- Stop/Reset planning draft mà không mất credit; credit chỉ dùng khi confirm curriculum.
- Xem và tải PDF/DOCX sau khi hoàn tất.
- Gửi yêu cầu hỗ trợ trực tiếp tới email Admin qua biểu mẫu công khai có validation và giới hạn tần suất.
- User Advanced settings và Admin System Config theo registry từ backend.
- Dashboard quản trị user, textbook, landing page VI/EN, plan, payment và system config.

## Tech Stack

- React 19 + Vite 8
- React Router 7
- Axios
- Tailwind CSS 3
- `i18next` + `react-i18next`
- `react-markdown`, GFM, KaTeX
- `react-hot-toast`, `react-icons`

## Requirements

- Node.js 20+
- npm
- Backend chạy tại `http://localhost:8000` hoặc URL được cấu hình qua biến môi trường

## Setup

```bash
cd frontend
npm install
```

Tạo hoặc cập nhật `frontend/.env`:

```env
VITE_API_URL=http://localhost:8000
```

Khởi động development server:

```bash
npm run dev
```

Frontend mặc định chạy tại `http://localhost:5173`.

## Scripts

| Command | Purpose |
|---|---|
| `npm run dev` | Chạy Vite development server với HMR |
| `npm run build` | Tạo production bundle trong `dist/` |
| `npm run lint` | Chạy ESLint cho toàn frontend |
| `npm run preview` | Preview production bundle cục bộ |

Trước khi commit thay đổi frontend:

```bash
npm run lint
npm run build
```

## Application Routes

Public/auth:

| Route | Page |
|---|---|
| `/` | Landing page |
| `/login` | Đăng nhập |
| `/register` | Đăng ký |
| `/forgot-password` | Yêu cầu OTP reset password |
| `/reset-password` | Xác nhận OTP và đặt mật khẩu mới |
| `/auth/callback` | Google OAuth callback |
| `/privacy-policy` | Chính sách quyền riêng tư và xử lý AI |
| `/terms-of-service` | Điều khoản sử dụng |
| `/data-deletion` | Quy trình yêu cầu xóa tài khoản và dữ liệu |
| `/support` | Hướng dẫn và biểu mẫu gửi yêu cầu tới Admin |
| `/contact` | Thông tin đơn vị vận hành và liên hệ |

Authenticated user:

| Route | Page |
|---|---|
| `/dashboard` | Danh sách và trạng thái giáo trình |
| `/create` | Tạo planning draft mới |
| `/create/:textbookId` | Tiếp tục theo dõi/review một textbook |
| `/textbooks/:id` | Chi tiết và file xuất bản |
| `/profile` | Credits, đổi mật khẩu và Advanced settings |

Admin:

| Route | Page |
|---|---|
| `/admin` | Dashboard thống kê |
| `/admin/users` | Quản lý user |
| `/admin/textbooks` | Theo dõi textbook |
| `/admin/landing` | Chỉnh landing config riêng cho VI/EN |
| `/admin/plans` | Quản lý plan và bank config |
| `/admin/payments` | Duyệt giao dịch |
| `/admin/config` | System defaults, API keys và audit |

`ProtectedRoute` bảo vệ route người dùng; `AdminRoute` yêu cầu quyền admin.

## Internationalization

i18n được khởi tạo tại `src/i18n/index.js`:

- Supported languages: `vi`, `en`
- Default: `vi`
- Storage key: `app_language`
- Fallback language: `vi`
- Locale resources: `src/i18n/locales/vi.js` và `src/i18n/locales/en.js`
- Khi đổi ngôn ngữ, app cập nhật cả `localStorage` và `document.documentElement.lang`

Component dùng `useTranslation()` và key từ locale resources. Các validation error phía client được lưu dưới dạng i18n descriptor trong `src/utils/formErrors.js`, nhờ đó message đang hiển thị đổi ngay khi user chuyển VI/EN.

`CreateTextbookPage` gửi ngôn ngữ UI hiện tại qua `ui_language`. Backend dùng giá trị này cho feedback/error và làm fallback khi query mơ hồ; ngôn ngữ giáo trình vẫn được Validator suy luận từ query. Không có selector ngôn ngữ giáo trình trong Advanced settings.

Khi thêm text mới:

1. Thêm cùng key vào cả `vi.js` và `en.js`.
2. Dùng `t('namespace.key')` hoặc `Trans`, không hard-code text trong JSX.
3. Với lỗi cần đổi ngôn ngữ ngay trên màn hình, dùng helper trong `formErrors.js` thay vì lưu chuỗi đã dịch.
4. Chạy `rg -n '[À-ỹ]' frontend/src` để rà text tiếng Việt hard-code có thể bị sót.

## Textbook Workflow

1. Form gửi topic, số chapter, content level, giới hạn subsection, image option và `ui_language`.
2. Backend validate topic/ngôn ngữ và tạo planning draft với `credits_used=0`.
3. UI poll `/textbooks/{id}/progress` đến phase `reviewing`.
4. User chỉnh curriculum hoặc thêm/xóa chapter/subsection.
5. Stop hoặc Reset ở planning/review xóa draft và quay về form; credit không bị trừ.
6. Confirm curriculum khóa request trong lúc xử lý; backend trừ 1 credit và bắt đầu generation.
7. UI tiếp tục poll progress, render content preview và đồng bộ counters qua `src/utils/progressMetrics.js`.
8. Khi hoàn tất, user mở trang detail để tải PDF/DOCX.

Các phase/status từ backend được map sang i18n key ở frontend. Dữ liệu do user, admin hoặc database tạo ra được giữ nguyên nếu không có mapping.

## Landing Configuration

Landing page có config riêng theo ngôn ngữ trong `src/utils/landingConfig.js`:

- Defaults: `DEFAULT_CONFIGS.vi` và `DEFAULT_CONFIGS.en`
- Storage key: `landing_page_config_v2_<language>`
- Config cũ `landing_page_config_v1` được migrate sang bản tiếng Việt khi cần
- Admin reset chỉ tác động đến ngôn ngữ đang chỉnh
- Landing config chỉ quản lý nội dung marketing; footer và thông tin liên hệ không còn lưu trong localStorage

Thông tin website/liên hệ được lưu trong table `site_contact_config` và chỉnh tại Admin System Configuration. `SiteFooter` được đặt ở cấp ứng dụng, dùng các nhóm liên kết cố định và đọc tên dịch vụ, địa chỉ, email, điện thoại từ API theo ngôn ngữ hiện tại.

## Project Structure

```text
src/
|-- api/                 # Axios instance và API clients
|-- components/
|   |-- common/          # Language switcher, badge, pagination...
|   |-- layout/          # Navbar và admin navigation
|   |-- settings/        # User Advanced settings
|   |-- textbooks/       # Form, editor, progress và content preview
|   |-- topup/           # Plan, payment và transaction UI
|-- context/             # Authentication state
|-- i18n/                # i18next setup và VI/EN resources
|-- pages/               # Public, auth, user và admin pages
|-- utils/               # Error mapping, landing config, progress metrics
|-- App.jsx              # Route definitions
|-- main.jsx             # React entry point và i18n bootstrap
```

## API Notes

- Axios base URL lấy từ `VITE_API_URL`, fallback `http://localhost:8000`.
- Access token được lưu với key `token` và gắn vào `Authorization: Bearer ...`.
- Response `401` sẽ xóa token và chuyển về `/login`.
- API prefix `/api/v1` được cấu hình trong Axios client.
- `GET /api/v1/site-info?language=vi|en` cung cấp thông tin liên hệ public; Admin quản lý qua `GET/PUT /api/v1/admin/site-info`.
- Form hỗ trợ gọi `POST /api/v1/support/requests`; backend ưu tiên email hỗ trợ trong `site_contact_config`, sau đó fallback về email của tài khoản Admin đang hoạt động.

Xem [README gốc](../README.md) để cài backend, MySQL, Redis, Celery, Pandoc/Typst và chạy migration.
