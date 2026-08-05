# Member Role Report — Day 9: Multi Agent A2A

## 1. Thông tin cá nhân

| Thông tin       | Nội dung |
| --------------- | ------------ |
| Họ và tên       | Nguyễn Sỹ Mạnh Cường |
| MSSV            | 2A202601040 |
| Khóa/Lớp        | K4 |
| Vai trò chính   | Multi-Agent Architecture & Pipeline Lead |
| Ngày hoàn thành | 2026-08-05 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| ------------------ | ------------------ | -------------- | ----------------- | ------------------------------------- |
| Multi-Agent Architecture & Orchestrator | `src/orchestrator.py`, `src/agents.py` | `input/EC_xxx.json` + Olist Data | `output/EC_xxx.json`, `trace.jsonl` | Hoàn thành |
| Data Loader & Rule Engine | `src/data_loader.py`, `src/llm_client.py` | Olist CSVs | Clean Case Entities & Calculations | Hoàn thành |
| Pipeline Execution & Config | `src/main.py`, `src/config.py` | Configuration & CLI | 50 Executed Output Files + Metadata | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| ------------------------- | ----------------------------- | ----------------------- |
| System Architecture & Diagram | Nhóm | Hoàn thiện `architecture.md` chuẩn Mermaid |
| Metadata & Submission Packaging | Nhóm | Hoàn thiện `metadata.json` và cấu trúc file nộp |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --------------------- | --------------------------- | ------------------------- | --------------- |
| Xây dựng 6 LLM Domain/Policy Agents + 1 Verifier Agent | `src/agents.py`, `src/orchestrator.py` | Hệ thống Multi-Agent chạy hoàn chỉnh cho 50 case | `python -m src.main` |
| Triển khai Handoff Trace Logger | `trace.jsonl` | Nhật ký chi tiết vết thực thi handoff giữa các agents | Check entries trong `trace.jsonl` |
| Tuân thủ Output Schema EC_POLICY_V2 | `src/orchestrator.py` | 50 file JSON chuẩn schema | `output/EC_001.json` - `EC_050.json` |

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Bài toán yêu cầu điều tra 50 ca khiếu nại thương mại điện tử từ bộ dữ liệu Olist. Mỗi ca khiếu nại đòi hỏi đối soát mốc thời gian (giao hàng, bàn giao carrier), giá trị đơn hàng (price + freight vs payment), lịch sử khách hàng và áp dụng bộ quy tắc ưu tiên `EC_POLICY_V2` để xác định primary/secondary issues, bên chịu trách nhiệm và mức hoàn tiền.

### Cách triển khai

Hệ thống được thiết kế theo kiến trúc **Hierarchical Multi-Agent Orchestration**:
1. **Coordinator Agent** (`ministral-8b-2512`): Tiếp nhận case input, điều phối 4 domain agents.
2. **Customer Agent** (`ministral-3b-2512`): Tra cứu `customer_unique_id` và xác định `repeat_customer`.
3. **Order & Product Agent** (`ministral-3b-2512`): Trích xuất items, sellers, products, categories.
4. **Delivery Agent** (`ministral-3b-2512`): Tính `delivery_variance_hours`, `handoff_variance_hours` per seller.
5. **Payment Agent** (`ministral-3b-2512`): Đối soát `expected_total` vs `payment_total`, xác định `reconciled`.
6. **Policy Agent** (`ministral-8b-2512`): Áp dụng thứ tự ưu tiên quy tắc `EC_POLICY_V2`.
7. **Verifier Agent** (`meta/llama-3.2-3b-instruct`): Cross-check schema và các ràng buộc mảng trước khi lưu output.

### Input, output và contract

| Thành phần | Mô tả |
| ----------------------- | -------------------------------------- |
| Input | `input/EC_xxx.json` (case_id, claimed_order_id, policy_version) |
| Output | `output/EC_xxx.json` (case_assessment, affected_entities, delivery_analysis, payment_reconciliation, evidence_ids, financial_resolution, resolution_actions) |
| Module phụ thuộc | `requests`, `pandas`, `concurrent.futures` |
| Module sử dụng output | Chấm điểm tự động competition leaderboard |
| Điều kiện lỗi cần xử lý | Network timeout, JSON unparseable, missing CSV values |

### Cách xác minh

```bash
$env:PYTHONIOENCODING="utf-8"; python -m src.main
```

- **Kết quả mong đợi:** Sinh đủ 50 file JSON trong `output/` và file `trace.jsonl`.
- **Kết quả thực tế:** 50/50 file JSON sinh đúng chuẩn schema, không bị nổ ngoại lệ.
- **Artifact/log:** `trace.jsonl`, `logging/metadata.json`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Lựa chọn giữa gọi 1 LLM duy nhất (Single-prompt) vs Kiến trúc Multi-Agent thực sự có Handoff & Hybrid Computation.
- **Các phương án đã cân nhắc:**
  1. Single LLM Prompt: Dễ cài đặt nhưng dễ bị hallucination số liệu (delivery variance, payment diff).
  2. Multi-Agent Hybrid (Python Data Loader + Concurrent LLM Agents): Kết hợp sức mạnh tính toán số liệu chính xác của Python với khả năng suy luận ngữ cảnh của các LLM Agents (Mistral 8B/3B & Llama 3B).
- **Phương án đã chọn:** Phương án 2 (Multi-Agent Hybrid Architecture).
- **Lý do:** Đáp ứng đúng yêu cầu bài lab về Multi-Agent handoff, phân định vai trò rõ ràng, kiểm soát tuyệt đối tính chính xác của dữ liệu tài chính và thời gian.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** `HTTPSConnectionPool(host='integrate.api.nvidia.com', port=443): Read timed out.` khi Verifier Agent gọi NVIDIA NIM API.
- **Lệnh hoặc bước tái hiện:** Chạy pipeline và quan sát tiến trình dừng lại ở bước Verifier.
- **Nguyên nhân gốc:** Endpoint NVIDIA NIM bị nghẽn mạng / timeout từ môi trường cục bộ.
- **Cách xử lý:** Thêm cơ chế **Automatic Fallback** trong `llm_client.py`: nếu NVIDIA API không phản hồi trong 5 giây, tự động chuyển sang gọi Mistral API (`ministral-3b-2512`).
- **Cách xác minh sau khi sửa:** Pipeline chạy mượt mà end-to-end cho cả 50 case mà không bị treo.
- **Điều học được:** Luôn có chiến lược fallback (resilience pattern) cho API bên ngoài trong các hệ thống Multi-Agent production.

## 7. Hiểu biết về luồng end-to-end

1. **Dữ liệu đi từ Crossref đến vector index như thế nào?**
   - Dữ liệu thô từ Crossref API (metadata bài báo khoa học) được crawl, làm sạch (clean HTML/abstract), chunking thành các đoạn nhỏ có kích thước phù hợp (overlap context), sau đó thông qua mô hình Embedding (ví dụ `text-embedding-3-small` hoặc `bge-m3`) để tạo ra vector embeddings và lưu vào Vector Index (Qdrant/FAISS/ChromaDB).
2. **Evaluation set và ground-truth document IDs dùng để đo retrieval/answer quality ra sao?**
   - Evaluation set bao gồm danh sách câu hỏi kiểm thử kèm danh sách `ground-truth document IDs` đáp án.
   - Để đo **Retrieval Quality**: So sánh danh sách top-K document IDs được truy vấn từ Vector DB với ground-truth IDs qua các chỉ số như `Hit Rate@K`, `MRR` (Mean Reciprocal Rank), `NDCG@K`.
   - Để đo **Answer Quality**: Dùng LLM-as-a-judge hoặc Rouge/BLEU/Faithfulness metric để đo độ chính xác của câu trả lời sinh ra so với context được retrieve.
3. **Quality checks khác freshness monitoring ở điểm nào trong bài lab?**
   - **Quality checks**: Kiểm tra tính đúng đắn, toàn vẹn của dữ liệu (schema validation, null check, format, outlier detection, embedding drift).
   - **Freshness monitoring**: Theo dõi mốc thời gian cập nhật của dữ liệu (data recency, timestamp latency) để đảm bảo index không bị out-of-date so với nguồn thực tế.
4. **Vì sao phải dùng cùng test set cho baseline, corrupted và repaired?**
   - Để đảm bảo tính công bằng và nhất quán trong đánh giá (Controlled Experiment). Việc giữ cố định test set giúp cô lập biến số duy nhất là chất lượng của pipeline (Baseline vs Corrupted vs Repaired), từ đó đo lường chính xác hiệu quả cải tiến (delta improvement).
5. **Repair được xem là thành công dựa trên artifact và metric nào?**
   - Repair thành công khi chỉ số retrieval (Hit Rate, MRR) và generation (Faithfulness, Correctness) của mô hình sau khi repair khôi phục về gần hoặc vượt mức Baseline trên cùng test set. Bằng chứng là bảng báo cáo so sánh metrics và các log artifacts (`evaluation_results.json`, `trace_log.jsonl`).

## 8. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Nguyễn Sỹ Mạnh Cường  
**Ngày xác nhận:** 2026-08-05
