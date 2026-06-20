export const PUBLIC_PAGE_CONTENT = {
  vi: {
    privacy: {
      eyebrow: 'Thông tin pháp lý',
      title: 'Chính sách quyền riêng tư',
      summary:
        'Chính sách này giải thích dữ liệu được thu thập, cách dữ liệu được sử dụng và các lựa chọn của bạn khi sử dụng Hệ Thống Tạo Giáo Trình AI.',
      sections: [
        {
          id: 'scope',
          title: '1. Phạm vi và đơn vị vận hành',
          paragraphs: [
            'Chính sách áp dụng cho website, tài khoản người dùng và các chức năng tạo, quản lý, thanh toán và xuất bản giáo trình của hệ thống. Thông tin đơn vị vận hành và kênh liên hệ chính thức được công bố ở cuối trang.',
            'Khi tiếp tục sử dụng dịch vụ, bạn xác nhận đã đọc chính sách này. Nếu không đồng ý với cách xử lý dữ liệu được mô tả, bạn nên ngừng sử dụng dịch vụ và có thể yêu cầu xóa dữ liệu theo hướng dẫn tương ứng.',
          ],
        },
        {
          id: 'data-collected',
          title: '2. Dữ liệu được thu thập',
          paragraphs: [
            'Tùy theo chức năng bạn sử dụng, hệ thống có thể xử lý các nhóm dữ liệu sau:',
          ],
          bullets: [
            'Thông tin tài khoản như họ tên, username, email, trạng thái tài khoản và phương thức đăng nhập.',
            'Thông tin hồ sơ cơ bản do Google OAuth cung cấp khi bạn chọn đăng nhập bằng Google. Hệ thống không nhận mật khẩu Google của bạn.',
            'Chủ đề, yêu cầu, cấu hình, đề cương đã chỉnh sửa, nội dung giáo trình và các tệp Markdown, PDF hoặc Word được tạo.',
            'Thông tin tín dụng, gói dịch vụ, giao dịch nạp tiền, nội dung chuyển khoản và trạng thái xác nhận thanh toán.',
            'Cấu hình nâng cao, lựa chọn ngôn ngữ, dữ liệu lưu trên trình duyệt và lịch sử thay đổi cấu hình.',
            'Dữ liệu kỹ thuật và bảo mật cần thiết để vận hành dịch vụ, chẳng hạn thời điểm truy cập, lỗi hệ thống và nhật ký tác vụ.',
          ],
        },
        {
          id: 'purposes',
          title: '3. Mục đích sử dụng dữ liệu',
          bullets: [
            'Tạo và bảo vệ tài khoản, xác thực người dùng và phân quyền quản trị.',
            'Phân tích yêu cầu, thu thập nguồn, tạo đề cương, sinh nội dung và xuất bản giáo trình.',
            'Theo dõi tiến độ, khôi phục tác vụ, lưu lịch sử và cung cấp tệp tải xuống.',
            'Xử lý tín dụng, yêu cầu nạp tiền, xác nhận giao dịch và phòng chống gian lận.',
            'Gửi email phục hồi tài khoản, phản hồi yêu cầu hỗ trợ và thông báo liên quan đến dịch vụ.',
            'Chẩn đoán lỗi, bảo vệ hệ thống, cải thiện độ ổn định và tuân thủ nghĩa vụ áp dụng.',
          ],
        },
        {
          id: 'providers',
          title: '4. Nhà cung cấp và bên thứ ba',
          paragraphs: [
            'Hệ thống sử dụng các dịch vụ bên thứ ba để thực hiện một số chức năng. Chỉ dữ liệu cần thiết cho từng nhiệm vụ mới được chuyển đến nhà cung cấp tương ứng.',
          ],
          bullets: [
            'Nhà cung cấp mô hình AI và embedding để xác thực chủ đề, lập kế hoạch, truy xuất, viết, kiểm duyệt và tạo hình ảnh.',
            'Dịch vụ tìm kiếm web và hình ảnh để thu thập nguồn phục vụ giáo trình.',
            'Google OAuth để đăng nhập, nhà cung cấp SMTP để gửi email và dịch vụ thanh toán/VietQR để hỗ trợ giao dịch.',
            'Hạ tầng cơ sở dữ liệu, hàng đợi tác vụ và lưu trữ tệp do đơn vị vận hành quản lý hoặc thuê sử dụng.',
          ],
        },
        {
          id: 'ai',
          title: '5. AI và xử lý tự động',
          paragraphs: [
            'Chủ đề, yêu cầu, ngữ cảnh truy xuất và nội dung cần thiết có thể được gửi đến các mô hình AI để tạo giáo trình. Kết quả được sinh tự động và có thể chứa sai sót, thông tin thiếu cập nhật hoặc cách diễn giải chưa phù hợp.',
            'Không sử dụng nội dung do hệ thống tạo ra như nguồn tư vấn y tế, pháp lý, tài chính hoặc quyết định có mức độ rủi ro cao. Người dùng chịu trách nhiệm kiểm tra dữ kiện, nguồn tham khảo và mức độ phù hợp trước khi giảng dạy, xuất bản hoặc sử dụng chính thức.',
          ],
        },
        {
          id: 'storage',
          title: '6. Lưu trữ, bảo mật và thời hạn giữ dữ liệu',
          paragraphs: [
            'Dữ liệu có thể được lưu trong MySQL, Redis, ChromaDB, thư mục tệp đầu ra và bộ nhớ trình duyệt. Hệ thống áp dụng các biện pháp kỹ thuật phù hợp như mã hóa mật khẩu, token xác thực, phân quyền và giới hạn truy cập quản trị.',
            'Dữ liệu được giữ trong thời gian cần thiết để cung cấp dịch vụ, giải quyết tranh chấp, bảo vệ an toàn hệ thống và đáp ứng nghĩa vụ kế toán hoặc pháp lý. Không có phương thức truyền hoặc lưu trữ điện tử nào bảo đảm an toàn tuyệt đối.',
          ],
        },
        {
          id: 'browser-storage',
          title: '7. Cookies và bộ nhớ trình duyệt',
          paragraphs: [
            'Ứng dụng sử dụng bộ nhớ trình duyệt để lưu token đăng nhập, ngôn ngữ giao diện và một số cấu hình hiển thị. Các nhà cung cấp OAuth hoặc dịch vụ bên ngoài có thể sử dụng cookies theo chính sách riêng của họ.',
          ],
        },
        {
          id: 'rights',
          title: '8. Quyền và lựa chọn của người dùng',
          bullets: [
            'Yêu cầu xem, điều chỉnh hoặc làm rõ dữ liệu tài khoản của bạn.',
            'Rút lại quyền truy cập Google từ trang quản lý tài khoản Google.',
            'Yêu cầu xóa tài khoản và dữ liệu theo trang Xóa dữ liệu.',
            'Đăng xuất hoặc xóa dữ liệu lưu cục bộ trên trình duyệt của bạn.',
            'Liên hệ để phản ánh vấn đề về quyền riêng tư hoặc an toàn dữ liệu.',
          ],
        },
        {
          id: 'changes',
          title: '9. Thay đổi chính sách',
          paragraphs: [
            'Chính sách có thể được cập nhật khi chức năng, nhà cung cấp hoặc yêu cầu áp dụng thay đổi. Phiên bản mới sẽ được đăng tại trang này cùng ngày hiệu lực được cập nhật.',
          ],
        },
      ],
    },
    terms: {
      eyebrow: 'Thông tin pháp lý',
      title: 'Điều khoản sử dụng',
      summary:
        'Các điều khoản dưới đây quy định việc truy cập và sử dụng Hệ Thống Tạo Giáo Trình AI.',
      sections: [
        {
          id: 'acceptance',
          title: '1. Chấp nhận điều khoản',
          paragraphs: [
            'Bằng việc đăng ký, đăng nhập hoặc sử dụng dịch vụ, bạn đồng ý tuân thủ các điều khoản này và Chính sách quyền riêng tư. Nếu sử dụng thay mặt một tổ chức, bạn xác nhận mình có quyền đại diện cho tổ chức đó.',
          ],
        },
        {
          id: 'accounts',
          title: '2. Tài khoản và bảo mật',
          bullets: [
            'Cung cấp thông tin đăng ký chính xác và cập nhật khi có thay đổi.',
            'Bảo vệ thông tin đăng nhập và chịu trách nhiệm đối với hoạt động phát sinh từ tài khoản của mình.',
            'Thông báo sớm khi phát hiện truy cập trái phép hoặc vấn đề bảo mật.',
            'Không chia sẻ, bán, chuyển nhượng hoặc sử dụng tài khoản của người khác khi chưa được phép.',
          ],
        },
        {
          id: 'acceptable-use',
          title: '3. Sử dụng được phép',
          paragraphs: [
            'Dịch vụ được cung cấp để hỗ trợ nghiên cứu, học tập và biên soạn tài liệu. Bạn không được sử dụng hệ thống cho hoạt động trái pháp luật, gây hại hoặc xâm phạm quyền của người khác.',
          ],
          bullets: [
            'Không nhập hoặc yêu cầu tạo nội dung bất hợp pháp, lạm dụng, thù ghét, xâm hại hoặc hướng dẫn hành vi nguy hiểm.',
            'Không tải lên dữ liệu cá nhân nhạy cảm, bí mật, nội dung có bản quyền hoặc tài liệu mà bạn không có quyền xử lý.',
            'Không cố gắng vượt qua kiểm soát truy cập, phá hoại dịch vụ, khai thác lỗ hổng hoặc làm gián đoạn hạ tầng.',
            'Không trình bày nội dung AI chưa được kiểm chứng như thông tin chắc chắn hoặc sản phẩm đã được chuyên gia phê duyệt.',
          ],
        },
        {
          id: 'ai-content',
          title: '4. Nội dung do AI tạo',
          paragraphs: [
            'Nội dung do hệ thống tạo ra có thể không chính xác hoàn toàn, có thể thiếu nguồn, chứa thiên kiến hoặc không phù hợp với bối cảnh cụ thể. Chức năng kiểm duyệt và Corrective RAG giúp giảm rủi ro nhưng không loại bỏ mọi sai sót.',
            'Bạn phải kiểm tra nội dung trước khi sử dụng. Dịch vụ không thay thế tư vấn y tế, pháp lý, tài chính hoặc đánh giá chuyên môn. Mọi quyết định dựa trên nội dung tạo sinh thuộc trách nhiệm của người sử dụng.',
          ],
        },
        {
          id: 'content-rights',
          title: '5. Nội dung và quyền sử dụng',
          paragraphs: [
            'Bạn chịu trách nhiệm bảo đảm mình có quyền cung cấp chủ đề, tài liệu và yêu cầu đầu vào. Bạn cho phép hệ thống xử lý các nội dung đó trong phạm vi cần thiết để cung cấp dịch vụ.',
            'Quyền đối với kết quả tạo sinh phụ thuộc vào pháp luật áp dụng, quyền của bên thứ ba và điều khoản của các nhà cung cấp liên quan. Bạn có trách nhiệm kiểm tra bản quyền, trích dẫn và quyền sử dụng trước khi công bố hoặc khai thác thương mại.',
          ],
        },
        {
          id: 'credits',
          title: '6. Tín dụng và thanh toán',
          paragraphs: [
            'Hệ thống có thể yêu cầu tín dụng để bắt đầu tạo nội dung sau khi đề cương được xác nhận. Bản nháp ở giai đoạn lập kế hoạch không bị trừ tín dụng nếu người dùng dừng hoặc đặt lại trước khi xác nhận.',
            'Giao dịch nạp tiền chỉ được ghi nhận sau khi được xác nhận theo quy trình thanh toán. Trừ khi pháp luật yêu cầu khác, tín dụng đã dùng để bắt đầu quá trình tạo giáo trình không được hoàn lại khi người dùng chủ động dừng tác vụ.',
          ],
        },
        {
          id: 'availability',
          title: '7. Tính sẵn sàng và thay đổi dịch vụ',
          paragraphs: [
            'Dịch vụ có thể bị gián đoạn do bảo trì, lỗi nhà cung cấp, giới hạn API hoặc nguyên nhân ngoài khả năng kiểm soát. Chức năng, giới hạn và mô hình được sử dụng có thể thay đổi để cải thiện an toàn hoặc hiệu quả vận hành.',
          ],
        },
        {
          id: 'termination',
          title: '8. Tạm ngừng và chấm dứt tài khoản',
          paragraphs: [
            'Đơn vị vận hành có thể giới hạn, khóa hoặc chấm dứt tài khoản khi có dấu hiệu vi phạm điều khoản, gây rủi ro bảo mật, gian lận hoặc làm ảnh hưởng đến hệ thống và người dùng khác. Người dùng có thể yêu cầu xóa tài khoản theo quy trình Xóa dữ liệu.',
          ],
        },
        {
          id: 'liability',
          title: '9. Giới hạn trách nhiệm',
          paragraphs: [
            'Trong phạm vi pháp luật cho phép, dịch vụ được cung cấp theo tình trạng hiện có và không bảo đảm mọi kết quả sẽ chính xác, đầy đủ hoặc phù hợp cho một mục đích cụ thể. Đơn vị vận hành không chịu trách nhiệm đối với thiệt hại phát sinh từ việc sử dụng nội dung chưa được người dùng kiểm chứng.',
          ],
        },
        {
          id: 'changes-contact',
          title: '10. Thay đổi và liên hệ',
          paragraphs: [
            'Điều khoản có thể được cập nhật khi dịch vụ thay đổi. Việc tiếp tục sử dụng sau ngày hiệu lực của phiên bản mới thể hiện sự chấp nhận của bạn trong phạm vi pháp luật cho phép. Mọi câu hỏi có thể được gửi qua trang Liên hệ hoặc Hỗ trợ.',
          ],
        },
      ],
    },
    deletion: {
      eyebrow: 'Quyền dữ liệu',
      title: 'Yêu cầu xóa tài khoản',
      summary:
        'Bạn có thể yêu cầu vô hiệu hóa tài khoản và xóa hoặc ẩn danh thông tin nhận diện theo quy trình dưới đây.',
      sections: [
        {
          id: 'request',
          title: '1. Cách gửi yêu cầu',
          paragraphs: [
            'Sử dụng biểu mẫu ở đầu trang để gửi yêu cầu đến quản trị viên. Nếu đang đăng nhập, hệ thống sẽ lấy email và mã người dùng từ tài khoản hiện tại; nếu chưa đăng nhập, hãy nhập email đã dùng để đăng ký.',
          ],
          bullets: [
            'Cung cấp đúng email của tài khoản cần xóa.',
            'Chọn lý do và bổ sung ghi chú nếu cần để hỗ trợ quá trình xác minh.',
            'Không gửi mật khẩu, mã OTP, API key hoặc thông tin thanh toán.',
          ],
        },
        {
          id: 'verification',
          title: '2. Xác minh danh tính',
          paragraphs: [
            'Để bảo vệ tài khoản, đơn vị vận hành có thể yêu cầu xác minh quyền sở hữu email hoặc cung cấp thông tin cần thiết khác trước khi xóa. Yêu cầu có thể bị từ chối hoặc tạm dừng nếu không thể xác minh người gửi.',
          ],
        },
        {
          id: 'deleted-data',
          title: '3. Dữ liệu được xóa hoặc ẩn danh',
          bullets: [
            'Email, username, định danh Google, họ tên và ảnh đại diện của tài khoản.',
            'Mật khẩu, mã đặt lại mật khẩu, OTP và thông tin xác thực thuộc phạm vi kiểm soát của hệ thống.',
            'Token phiên, cấu hình cá nhân và dữ liệu tác vụ tạm thời có thể liên kết với tài khoản.',
            'Nội dung hỗ trợ không còn cần thiết để giải quyết yêu cầu hoặc tranh chấp.',
          ],
        },
        {
          id: 'retained-data',
          title: '4. Dữ liệu có thể được giữ lại',
          paragraphs: [
            'Mã nội bộ, bản ghi giáo trình, đề cương, dữ liệu tiến độ, tệp đầu ra và lịch sử giao dịch có thể được giữ ở trạng thái không còn gắn với thông tin nhận diện trực tiếp để bảo toàn quan hệ dữ liệu, kế toán, phòng chống gian lận, bảo mật, giải quyết tranh chấp hoặc nghĩa vụ pháp lý. Dữ liệu sao lưu có thể cần thêm thời gian để hết hạn theo chu kỳ vận hành.',
          ],
        },
        {
          id: 'google',
          title: '5. Dữ liệu đăng nhập Google',
          paragraphs: [
            'Nếu đã đăng nhập bằng Google, bạn có thể thu hồi quyền truy cập của ứng dụng tại phần quản lý kết nối với ứng dụng bên thứ ba trong Tài khoản Google. Việc thu hồi quyền không tự động xóa dữ liệu đã lưu trong hệ thống; bạn vẫn cần gửi yêu cầu xóa theo quy trình trên.',
          ],
        },
        {
          id: 'local-data',
          title: '6. Dữ liệu trên thiết bị của bạn',
          paragraphs: [
            'Sau khi yêu cầu được xử lý, bạn nên đăng xuất và xóa dữ liệu website trong trình duyệt để loại bỏ token, lựa chọn ngôn ngữ và cấu hình được lưu cục bộ.',
          ],
        },
        {
          id: 'processing-time',
          title: '7. Thời gian xử lý',
          paragraphs: [
            'Yêu cầu sẽ được phản hồi và xử lý trong thời gian hợp lý tùy theo phạm vi, khả năng xác minh và nghĩa vụ áp dụng. Bạn sẽ được thông báo nếu cần thêm thông tin hoặc nếu một phần dữ liệu không thể xóa ngay.',
          ],
        },
      ],
    },
    support: {
      eyebrow: 'Trung tâm trợ giúp',
      title: 'Hỗ trợ',
      summary:
        'Liên hệ đội ngũ hỗ trợ khi bạn gặp vấn đề về tài khoản, tạo giáo trình, thanh toán hoặc dữ liệu.',
      sections: [
        {
          id: 'channels',
          title: '1. Kênh hỗ trợ',
          paragraphs: [
            'Bạn có thể gửi yêu cầu trực tiếp bằng biểu mẫu trên trang này. Hệ thống sẽ chuyển nội dung tới email hỗ trợ hoặc tài khoản quản trị viên đã được cấu hình.',
          ],
        },
        {
          id: 'include',
          title: '2. Thông tin nên cung cấp',
          bullets: [
            'Email hoặc username tài khoản, nhưng không gửi mật khẩu hay mã OTP.',
            'Mô tả ngắn vấn đề, thời điểm xảy ra và thao tác ngay trước lỗi.',
            'ID giáo trình hoặc ID giao dịch nếu vấn đề liên quan đến tác vụ cụ thể.',
            'Ảnh chụp màn hình và thông báo lỗi sau khi đã che dữ liệu nhạy cảm.',
            'Ngôn ngữ giao diện và trình duyệt đang sử dụng nếu lỗi liên quan đến hiển thị.',
          ],
        },
        {
          id: 'account',
          title: '3. Tài khoản và đăng nhập',
          paragraphs: [
            'Sử dụng chức năng Quên mật khẩu để nhận mã OTP nếu tài khoản local không đăng nhập được. Với tài khoản Google, hãy kiểm tra đúng tài khoản Google đã đăng ký. Liên hệ hỗ trợ nếu tài khoản bị khóa hoặc không nhận được email.',
          ],
        },
        {
          id: 'generation',
          title: '4. Tạo giáo trình',
          paragraphs: [
            'Nếu tác vụ dừng hoặc báo lỗi, hãy ghi lại ID giáo trình và thông báo hiển thị. Không gửi lại xác nhận liên tục. Planning draft có thể được đặt lại mà không trừ tín dụng; tác vụ đã xác nhận có thể đã sử dụng tín dụng theo Điều khoản sử dụng.',
          ],
        },
        {
          id: 'payments',
          title: '5. Thanh toán và tín dụng',
          paragraphs: [
            'Khi yêu cầu kiểm tra giao dịch, cung cấp mã giao dịch, nội dung chuyển khoản và thời điểm thanh toán. Không đăng công khai ảnh chứa đầy đủ thông tin tài khoản ngân hàng.',
          ],
        },
        {
          id: 'security',
          title: '6. Báo cáo vấn đề bảo mật',
          paragraphs: [
            'Nếu phát hiện lỗ hổng hoặc truy cập trái phép, hãy gửi thông tin qua email quyền riêng tư hoặc email hỗ trợ. Không khai thác sâu, công bố dữ liệu người dùng hoặc làm gián đoạn hệ thống trong quá trình báo cáo.',
          ],
        },
      ],
    },
    contact: {
      eyebrow: 'Kết nối với chúng tôi',
      title: 'Liên hệ',
      summary:
        'Thông tin liên hệ chính thức của đơn vị vận hành Hệ Thống Tạo Giáo Trình AI.',
      sections: [
        {
          id: 'general',
          title: 'Liên hệ chung',
          paragraphs: [
            'Sử dụng email hỗ trợ cho câu hỏi về tài khoản, giáo trình và thanh toán. Đối với yêu cầu quyền riêng tư, xóa dữ liệu hoặc báo cáo an toàn, hãy sử dụng email quyền riêng tư.',
          ],
        },
        {
          id: 'before-contacting',
          title: 'Trước khi liên hệ',
          bullets: [
            'Không gửi mật khẩu, mã OTP, API key hoặc thông tin thanh toán đầy đủ.',
            'Cung cấp ID liên quan và mô tả đủ chi tiết để hỗ trợ xác định vấn đề.',
            'Che dữ liệu cá nhân không cần thiết trong ảnh chụp màn hình.',
            'Với yêu cầu xóa dữ liệu, gửi từ email đã đăng ký tài khoản.',
          ],
        },
      ],
    },
  },
  en: {
    privacy: {
      eyebrow: 'Legal information',
      title: 'Privacy Policy',
      summary:
        'This policy explains what data is collected, how it is used, and the choices available to you when using AI Textbook Generator.',
      sections: [
        {
          id: 'scope',
          title: '1. Scope and operator',
          paragraphs: [
            'This policy applies to the website, user accounts, and the textbook generation, management, payment, and publishing features of the service. Operator and official contact details are listed at the bottom of this page.',
            'By continuing to use the service, you acknowledge that you have read this policy. If you disagree with the described processing, stop using the service and request deletion where appropriate.',
          ],
        },
        {
          id: 'data-collected',
          title: '2. Data we collect',
          paragraphs: ['Depending on the features you use, the service may process:'],
          bullets: [
            'Account details such as name, username, email, account status, and authentication method.',
            'Basic profile details supplied by Google OAuth when you choose Google sign-in. We do not receive your Google password.',
            'Topics, instructions, settings, edited outlines, generated textbook content, and Markdown, PDF, or Word files.',
            'Credit balances, plans, top-up transactions, transfer references, and payment review status.',
            'Advanced configuration, language preferences, browser-stored data, and configuration audit history.',
            'Technical and security data required to operate the service, including timestamps, errors, and task logs.',
          ],
        },
        {
          id: 'purposes',
          title: '3. How we use data',
          bullets: [
            'Create and protect accounts, authenticate users, and enforce roles.',
            'Analyze requests, collect sources, plan, write, review, and publish textbooks.',
            'Track progress, recover tasks, retain history, and provide downloads.',
            'Process credits and top-ups, verify transactions, and prevent fraud.',
            'Send account recovery email, answer support requests, and deliver service notices.',
            'Diagnose failures, secure the system, improve reliability, and meet applicable obligations.',
          ],
        },
        {
          id: 'providers',
          title: '4. Service providers and third parties',
          paragraphs: [
            'The service relies on third parties for certain functions. Only data needed for the relevant task is sent to each provider.',
          ],
          bullets: [
            'AI model and embedding providers for validation, planning, retrieval, writing, review, and image generation.',
            'Web and image search services used to gather textbook sources.',
            'Google OAuth for sign-in, SMTP providers for email, and payment/VietQR services for transactions.',
            'Database, task queue, and file storage infrastructure operated or contracted by the service operator.',
          ],
        },
        {
          id: 'ai',
          title: '5. AI and automated processing',
          paragraphs: [
            'Topics, instructions, retrieved context, and relevant content may be sent to AI models to generate textbooks. Automated results can contain errors, outdated information, or unsuitable interpretations.',
            'Do not rely on generated content as medical, legal, financial, or other high-stakes professional advice. You are responsible for verifying facts, sources, and suitability before teaching, publishing, or otherwise relying on the output.',
          ],
        },
        {
          id: 'storage',
          title: '6. Storage, security, and retention',
          paragraphs: [
            'Data may be stored in MySQL, Redis, ChromaDB, output directories, and browser storage. The service applies reasonable controls such as password hashing, authentication tokens, authorization, and restricted administrative access.',
            'Data is retained as needed to provide the service, resolve disputes, protect the system, and meet accounting or legal obligations. No electronic storage or transmission method is completely secure.',
          ],
        },
        {
          id: 'browser-storage',
          title: '7. Cookies and browser storage',
          paragraphs: [
            'The application uses browser storage for authentication tokens, UI language, and selected display settings. OAuth and other third-party providers may use cookies under their own policies.',
          ],
        },
        {
          id: 'rights',
          title: '8. Your rights and choices',
          bullets: [
            'Request access to, correction of, or clarification about your account data.',
            'Revoke Google access through your Google Account settings.',
            'Request deletion of your account and related data through the Data Deletion page.',
            'Log out or remove locally stored site data from your browser.',
            'Contact us about privacy or data security concerns.',
          ],
        },
        {
          id: 'changes',
          title: '9. Changes to this policy',
          paragraphs: [
            'This policy may change as features, providers, or applicable requirements evolve. The updated version will be posted here with a revised effective date.',
          ],
        },
      ],
    },
    terms: {
      eyebrow: 'Legal information',
      title: 'Terms of Service',
      summary: 'These terms govern access to and use of AI Textbook Generator.',
      sections: [
        {
          id: 'acceptance',
          title: '1. Acceptance',
          paragraphs: [
            'By registering, signing in, or using the service, you agree to these terms and the Privacy Policy. If you use the service for an organization, you confirm that you are authorized to represent it.',
          ],
        },
        {
          id: 'accounts',
          title: '2. Accounts and security',
          bullets: [
            'Provide accurate registration information and keep it current.',
            'Protect your credentials and accept responsibility for activity under your account.',
            'Notify us promptly if you discover unauthorized access or a security issue.',
            'Do not sell, transfer, share, or use another person’s account without permission.',
          ],
        },
        {
          id: 'acceptable-use',
          title: '3. Acceptable use',
          paragraphs: [
            'The service supports research, learning, and educational content creation. You may not use it for illegal, harmful, or rights-infringing activity.',
          ],
          bullets: [
            'Do not request illegal, abusive, hateful, exploitative, or dangerous instructions.',
            'Do not submit sensitive personal data, confidential material, copyrighted content, or other data you have no right to process.',
            'Do not bypass access controls, disrupt the service, exploit vulnerabilities, or interfere with infrastructure.',
            'Do not present unverified AI output as guaranteed fact or expert-approved material.',
          ],
        },
        {
          id: 'ai-content',
          title: '4. AI-generated content',
          paragraphs: [
            'Generated content may be inaccurate, incomplete, biased, outdated, or unsuitable for a specific context. Review and Corrective RAG features reduce risk but cannot eliminate all errors.',
            'You must review output before use. The service does not replace medical, legal, financial, or other professional advice. You are responsible for decisions made using generated content.',
          ],
        },
        {
          id: 'content-rights',
          title: '5. Content and usage rights',
          paragraphs: [
            'You are responsible for ensuring that you may submit topics, materials, and instructions. You authorize the service to process them as needed to provide its features.',
            'Rights in generated output depend on applicable law, third-party rights, and provider terms. You must review copyright, attribution, and usage permissions before publishing or commercial use.',
          ],
        },
        {
          id: 'credits',
          title: '6. Credits and payments',
          paragraphs: [
            'The service may require one credit to begin content generation after you confirm an outline. A planning draft is not charged when it is stopped or reset before confirmation.',
            'Top-ups are credited only after payment review. Unless applicable law requires otherwise, a credit used to begin textbook generation is not refundable when you voluntarily stop the task.',
          ],
        },
        {
          id: 'availability',
          title: '7. Availability and changes',
          paragraphs: [
            'The service may be interrupted by maintenance, provider failures, API limits, or events beyond our control. Features, limits, and models may change to improve safety and operations.',
          ],
        },
        {
          id: 'termination',
          title: '8. Suspension and termination',
          paragraphs: [
            'The operator may limit, lock, or terminate an account where there is evidence of a terms violation, security risk, fraud, or harm to the service or other users. You may request account deletion through the Data Deletion process.',
          ],
        },
        {
          id: 'liability',
          title: '9. Limitation of liability',
          paragraphs: [
            'To the extent permitted by law, the service is provided as available without a guarantee that every result will be accurate, complete, or fit for a particular purpose. The operator is not responsible for losses arising from reliance on output that the user did not verify.',
          ],
        },
        {
          id: 'changes-contact',
          title: '10. Changes and contact',
          paragraphs: [
            'Terms may be updated as the service changes. Continued use after the effective date of an updated version constitutes acceptance where permitted by law. Questions may be sent through the Contact or Support page.',
          ],
        },
      ],
    },
    deletion: {
      eyebrow: 'Data rights',
      title: 'Account Deletion Request',
      summary: 'You can request account deactivation and deletion or anonymization of identifying information using the process below.',
      sections: [
        {
          id: 'request',
          title: '1. Submit a request',
          paragraphs: [
            'Use the form at the top of this page to notify an administrator. If you are signed in, the system uses your current account email and user ID; otherwise, enter the email used to register the account.',
          ],
          bullets: [
            'Provide the correct email address for the account to be deleted.',
            'Select a reason and add optional notes that may help with verification.',
            'Never submit passwords, OTP codes, API keys, or payment information.',
          ],
        },
        {
          id: 'verification',
          title: '2. Identity verification',
          paragraphs: [
            'To protect accounts, the operator may verify email ownership or request other necessary information before deletion. A request may be denied or paused if the requester cannot be verified.',
          ],
        },
        {
          id: 'deleted-data',
          title: '3. Data deleted or anonymized',
          bullets: [
            'Account email, username, Google identifier, full name, and avatar.',
            'Passwords, reset codes, OTP data, and authentication information controlled by the service.',
            'Session tokens, personal configuration, and temporary task data linked to the account.',
            'Support content no longer needed to handle the request or a dispute.',
          ],
        },
        {
          id: 'retained-data',
          title: '4. Data we may retain',
          paragraphs: [
            'Internal identifiers, textbook records, outlines, progress data, output files, and transaction history may be retained without direct identifying information to preserve data relationships and meet accounting, fraud-prevention, security, dispute-resolution, or legal obligations. Backups may take additional time to expire under normal retention cycles.',
          ],
        },
        {
          id: 'google',
          title: '5. Google sign-in data',
          paragraphs: [
            'If you used Google sign-in, you can revoke access in the third-party connections area of your Google Account. Revocation does not automatically delete data stored by this service; submit a deletion request as described above.',
          ],
        },
        {
          id: 'local-data',
          title: '6. Data on your device',
          paragraphs: [
            'After the request is completed, log out and clear this site’s browser data to remove locally stored authentication tokens, language settings, and configuration.',
          ],
        },
        {
          id: 'processing-time',
          title: '7. Processing time',
          paragraphs: [
            'Requests are acknowledged and handled within a reasonable period based on scope, verification, and applicable obligations. We will tell you if more information is needed or some data cannot be deleted immediately.',
          ],
        },
      ],
    },
    support: {
      eyebrow: 'Help center',
      title: 'Support',
      summary: 'Contact support for help with accounts, textbook generation, payments, or data.',
      sections: [
        {
          id: 'channels',
          title: '1. Support channels',
          paragraphs: [
            'You can submit a request directly through the form on this page. The system forwards it to the configured support address or an active administrator account.',
          ],
        },
        {
          id: 'include',
          title: '2. What to include',
          bullets: [
            'Your account email or username, but never your password or OTP.',
            'A short description, when the issue happened, and the preceding action.',
            'The textbook or transaction ID when the issue concerns a specific record.',
            'A screenshot and error message after removing sensitive information.',
            'Your UI language and browser when the issue concerns display behavior.',
          ],
        },
        {
          id: 'account',
          title: '3. Accounts and sign-in',
          paragraphs: [
            'Use Forgot Password to receive an OTP for local accounts. For Google accounts, verify that you selected the Google identity used during registration. Contact support if the account is locked or recovery email does not arrive.',
          ],
        },
        {
          id: 'generation',
          title: '4. Textbook generation',
          paragraphs: [
            'If a task stops or fails, record the textbook ID and displayed error. Do not repeatedly submit confirmation. Planning drafts can be reset without a credit charge; confirmed tasks may have consumed a credit under the Terms of Service.',
          ],
        },
        {
          id: 'payments',
          title: '5. Payments and credits',
          paragraphs: [
            'For transaction review, provide the transaction ID, transfer reference, and payment time. Do not post images containing full bank account information publicly.',
          ],
        },
        {
          id: 'security',
          title: '6. Security reports',
          paragraphs: [
            'Report vulnerabilities or unauthorized access through the privacy or support email. Do not exploit the issue further, disclose user data, or disrupt the service while reporting it.',
          ],
        },
      ],
    },
    contact: {
      eyebrow: 'Get in touch',
      title: 'Contact',
      summary: 'Official contact details for the operator of AI Textbook Generator.',
      sections: [
        {
          id: 'general',
          title: 'General inquiries',
          paragraphs: [
            'Use the support email for questions about accounts, textbooks, and payments. Use the privacy email for privacy rights, deletion requests, and safety reports.',
          ],
        },
        {
          id: 'before-contacting',
          title: 'Before contacting us',
          bullets: [
            'Never send passwords, OTPs, API keys, or full payment credentials.',
            'Provide relevant IDs and enough detail to identify the issue.',
            'Redact unnecessary personal data from screenshots.',
            'Send deletion requests from the email registered to the account.',
          ],
        },
      ],
    },
  },
}
