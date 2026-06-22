# AATG — Hướng dẫn tự chạy Experiment 1 và Experiment 2

Tài liệu này dùng cho người muốn tự tái lập hai thực nghiệm từ PDF và Markdown
nguồn trong `experiment/Data`. Chạy tất cả câu lệnh từ thư mục `experiment/`.

Các khối lệnh dùng cú pháp Bash/Git Bash với `\` để xuống dòng. Trong
PowerShell, chạy trên một dòng hoặc thay `\` bằng backtick `` ` ``.

## Yêu cầu môi trường

- Python 3.11 trở lên.
- OpenAI API key cho embedding của Experiment 1 và o3 judge của Experiment 2.
- NVIDIA NIM API key cho bốn NVIDIA judge.

```bash
python -m pip install -r requirements-experiment.txt
```

API key không được lưu sẵn trong code. Trong mọi lệnh có gọi API, tự thay:

```text
YOUR_OPENAI_API_KEY
YOUR_NVIDIA_API_KEY
```

bằng key tương ứng. Lưu ý rằng key truyền trên command line có thể được lưu
trong shell history.

## Cấu trúc dữ liệu

```text
experiment/
├── Data/
│   ├── PTIT/
│   ├── AATG/
│   └── DirectChat/
└── results/
```

Ba nguồn cùng sử dụng sáu topic:

```text
antoanhedieuhanh
laptrinhhuongdoituong
ngonngulaptrinhcpp
ngonngulaptrinhjava
nhapmoncnpm
nhapmonttnt
```

Mỗi nguồn có 6 file `full.md`. PTIT và AATG cũng giữ PDF nguồn. Các thư mục
`chapters/`, outline và `core_chapters.json` là dữ liệu dẫn xuất, không được lưu
sẵn và phải tạo lại trước khi chạy thực nghiệm.

## Phần 0 — Chuẩn bị dữ liệu và preflight

### 0.1 Trích outline từ 18 file Markdown

```bash
python extract_outline.py --root Data
```

Mỗi topic được tạo `outline.txt` và `outline.json` cạnh `full.md`.

### 0.2 Tách chapter

```bash
python split_chapters.py --root Data
```

Script chỉ đọc các file canonical tên `full.md` và tạo `chapters/chXX.md`.

### 0.3 Chọn năm chương dùng cho thực nghiệm

```bash
python select_core_chapters.py --root Data/PTIT
python select_core_chapters.py --root Data/AATG
python select_core_chapters.py --root Data/DirectChat
```

Mỗi sách được tạo `core_chapters.json` với đường dẫn tương đối. Sau bước này bộ
dữ liệu có 18 sách × 5 chương = 90 chương.

### 0.4 Preflight không gọi API

Kiểm tra Experiment 1:

```bash
python exp1_sdiv.py --preflight-only
```

Kết quả phải là `18 books, 90 chapters`.

Kiểm tra o3 và bốn NVIDIA judge:

```bash
python exp2_judge_openai.py --preflight-only
python exp2_judge_nvidia.py --judge nemotron49b --preflight-only
python exp2_judge_nvidia.py --judge mistral_nem --preflight-only
python exp2_judge_nvidia.py --judge llama70b --preflight-only
python exp2_judge_nvidia.py --judge qwen80b --preflight-only
```

Năm lệnh phải báo 18 sách, 90 chương và cùng một dataset fingerprint. Preflight
kiểm tra toàn bộ prompt và dừng nếu có prompt vượt `--max-input-tokens`; không có
nội dung chương nào bị cắt âm thầm.

## Phần 1 — Experiment 1: Semantic Diversity

### 1.1 Tính Sdiv

```bash
python exp1_sdiv.py \
  --openai-key "YOUR_OPENAI_API_KEY" \
  --output results/exp1
```

Lần đầu script embedding 90 chương bằng `text-embedding-3-small`. Những lần sau
`embedding_cache.json` được tái sử dụng nếu nội dung chương và model không đổi.

Các tùy chọn:

```text
--no-cache          embedding lại toàn bộ
--no-stopwords      không loại stop words tiếng Việt trước ROUGE-L
--phase embed       chỉ tạo cache embedding
--phase compute     chỉ tính pairwise
--phase aggregate   aggregate từ pairwise hiện có
--phase stats       tính lại thống kê từ textbook scores
```

Output chính:

```text
results/exp1/
├── embedding_cache.json
├── exp1_pairwise_raw.csv        # 180 dòng
├── exp1_textbook_scores.csv     # 18 dòng
├── exp1_group_scores.csv        # 3 dòng
└── exp1_stats.json
```

### 1.2 Vẽ biểu đồ

```bash
python exp1_plot.py \
  --input results/exp1 \
  --output results/exp1/figures \
  --dpi 300
```

Output gồm các hình `exp1_fig1*.png` và bảng `exp1_table_t1.csv/.txt`.

## Phần 2 — Experiment 2: Pedagogical Quality

Experiment 2 dùng đúng năm judge: OpenAI o3 và bốn NVIDIA model sau:

```text
nemotron49b  nvidia/llama-3.3-nemotron-super-49b-v1
mistral_nem  mistralai/mistral-nemotron
llama70b     meta/llama-3.3-70b-instruct
qwen80b      qwen/qwen3-next-80b-a3b-instruct
```

Mỗi judge chấm 90 chương × 3 run = 270 dòng.

### 2.1 Kiểm tra kết nối NVIDIA

Lệnh này thực hiện một request nhỏ cho mỗi model:

```bash
python test_nvidia_models.py \
  --api-key "YOUR_NVIDIA_API_KEY" \
  --output results/exp2_nvidia_model_check.json
```

Chỉ tiếp tục khi cả bốn model trả về `OK`.

### 2.2 Chạy OpenAI o3 judge

```bash
python exp2_judge_openai.py \
  --runs 3 \
  --workers 2 \
  --sleep 5 \
  --output results/exp2_o3 \
  --openai-key "YOUR_OPENAI_API_KEY"
```

Nếu bị ngắt, chạy lại đúng lệnh và thêm `--resume`:

```bash
python exp2_judge_openai.py \
  --runs 3 --workers 2 --sleep 5 \
  --output results/exp2_o3 \
  --openai-key "YOUR_OPENAI_API_KEY" \
  --resume
```

Nếu tài khoản có giới hạn TPM thấp, thêm `--tpm-limit NUMBER`.

### 2.3 Chạy bốn NVIDIA judge

Chạy mỗi lệnh trong một terminal riêng hoặc chạy tuần tự. Khi gặp HTTP 429, giảm
`--workers` xuống 1 và tăng `--sleep`.

```bash
python exp2_judge_nvidia.py \
  --judge nemotron49b \
  --runs 3 --workers 2 --sleep 3 \
  --output results/exp2_nemotron49b \
  --nvidia-key "YOUR_NVIDIA_API_KEY"
```

```bash
python exp2_judge_nvidia.py \
  --judge mistral_nem \
  --runs 3 --workers 2 --sleep 8 \
  --output results/exp2_mistral_nem \
  --nvidia-key "YOUR_NVIDIA_API_KEY"
```

```bash
python exp2_judge_nvidia.py \
  --judge llama70b \
  --runs 3 --workers 2 --sleep 3 \
  --output results/exp2_llama70b \
  --nvidia-key "YOUR_NVIDIA_API_KEY"
```

```bash
python exp2_judge_nvidia.py \
  --judge qwen80b \
  --runs 3 --workers 2 --sleep 5 \
  --output results/exp2_qwen80b \
  --nvidia-key "YOUR_NVIDIA_API_KEY"
```

Resume một NVIDIA judge bằng cách chạy lại đúng lệnh và thêm `--resume`. Resume
sẽ bị từ chối nếu model, dataset fingerprint, chapter hash hoặc output folder
không khớp.

Mỗi thư mục judge hoàn chỉnh có:

```text
exp2_chapter_scores.csv          # 270 dòng
exp2_textbook_scores.csv         # 18 dòng
exp2_group_scores.csv            # 3 dòng
exp2_stats.json
dataset_manifest.json
coverage_report.json             # complete = true
```

Nếu chỉ cần tạo lại group scores/stats từ textbook scores:

```bash
python exp2_aggregate.py \
  --input results/exp2_nemotron49b/exp2_textbook_scores.csv
```

### 2.4 Tính ensemble năm judge

```bash
python exp2_ensemble.py \
  --o3 results/exp2_o3 \
  --nemotron49b results/exp2_nemotron49b \
  --mistral-nem results/exp2_mistral_nem \
  --qwen80b results/exp2_qwen80b \
  --llama70b results/exp2_llama70b \
  --output results/exp2_ensemble
```

Ensemble từ chối judge chưa đủ 18 sách, coverage chưa hoàn chỉnh hoặc dataset
fingerprint không đồng nhất.

Output:

```text
results/exp2_ensemble/
├── exp2_ensemble_textbook_scores.csv     # 18 dòng
├── exp2_ensemble_group_scores.csv        # 3 dòng
├── exp2_ensemble_stats.json
└── exp2_ensemble_judge_summary.csv        # 15 dòng: 5 judge × 3 nguồn
```

### 2.5 Vẽ biểu đồ

```bash
python exp2_plot.py \
  --input results/exp2_ensemble \
  --output results/exp2_ensemble/figures \
  --dpi 300
```

Output gồm ba hình `exp2_fig2*.png` và bảng `exp2_table_t2.csv/.txt`.

## Thứ tự chạy đầy đủ

```text
0.1 extract_outline.py
0.2 split_chapters.py
0.3 select_core_chapters.py × 3 nguồn
0.4 Preflight Exp1 và Exp2
1.  exp1_sdiv.py
2.  exp1_plot.py
3.  test_nvidia_models.py
4.  exp2_judge_openai.py
5.  exp2_judge_nvidia.py × 4
6.  exp2_ensemble.py
7.  exp2_plot.py
```
