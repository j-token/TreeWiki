# 선택적 임베딩 검색

이 문서는 `.knowledge/config.yml`의 `embedding.enabled`가 `true`일 때만 읽는다.

## 안전 경계

- Markdown과 frontmatter를 권위 있는 원본으로 유지한다.
- 벡터 저장소는 삭제 후 재생성 가능한 파생 색인으로 취급한다.
- 사용자가 허용하지 않으면 문서를 외부 API로 전송하지 않는다.
- `embedding.mode: local_only` 문서는 원격 provider로 보내지 않는다.
- `embedding.mode: deny` 문서는 청크도 만들지 않는다.
- 원격 provider 장애 시 다른 provider로 자동 전환하지 않는다.
- `private`, `restricted`, `agent` 문서는 문서별 설정이 `allow`여도 원격 실행에서 제외한다.

## 설정

```yaml
version: 1
embedding:
  enabled: true
  execution: local
  remote_content_allowed: false
  provider: <저장소에서 확인한-provider>
  model: <저장소에서 확인한-model-id>
  index_path: .knowledge/index/
  chunk_target_tokens: 800
  chunk_max_tokens: 1000
  chunk_overlap_tokens: 120
retrieval:
  bm25_enabled: true
  bm25_index_path: .knowledge/index/search.db
  bm25_candidate_limit: 24
  bm25_result_limit: 12
  bm25_query_mode: high_recall
  result_content: locations_only
```

기존 provider, model, vector store와 환경 변수를 먼저 조사한다. 확인되지 않은 모델 ID를 만들지 않는다. 기존 구성이 없으면 구현 시점의 공식 자료를 확인한다.

## 색인

1. `active`이고 문서별 embedding 정책이 허용한 문서를 선택한다.
2. 헤딩 경로를 보존해 섹션 단위로 나눈다.
3. 긴 섹션만 설정된 최대 tokens에 맞춰 나눈다.
4. 정규화된 청크의 SHA-256을 계산한다.
5. 신규·변경 청크만 임베딩한다.
6. 삭제·폐기된 청크를 제거한다.
7. model ID나 vector 차원이 달라지면 전체 재색인한다.

`scripts/build_embedding_index.py`는 provider 중립 JSONL manifest를 만든다. 실제 벡터 계산은 저장소에서 확인한 provider adapter로 수행한다. `scripts/build_search_index.py`는 같은 원본에서 로컬 SQLite FTS5/BM25 색인을 만든다. 두 산출물은 `.knowledge/index/` 아래의 Git 제외 파생 데이터이며 삭제 후 재생성할 수 있다.

## 위치 전용 BM25 검색

SQLite BM25는 답을 만들거나 정확한 본문 조각을 잘라 주는 도구가 아니다. 관련 가능성이 있는 문서 위치를 넉넉하게 찾고, LLM이 `query read`로 선택한 원문을 직접 읽게 한다.

1. 호출자의 user/team/role/agent ACL로 허용 문서 ID를 먼저 계산한다.
2. 허용 ID만 SQLite 임시 테이블에 넣고 FTS5 순위 계산에 참여시킨다.
3. 통제어휘의 표준 키와 이명, 접두어, 한국어 연속 문자열의 2글자 토큰으로 질의를 확장한다.
4. 최소 점수 없이 OR 조건으로 BM25 후보를 최대 24개 수집한다.
5. 허용된 문서 관계를 1 hop 확장한 뒤 최대 12개 위치를 반환한다.
6. 결과에는 `path`, `id`, `rank`, `via`, `engine`만 둔다. 제목, 요약, 본문, snippet과 생성 답변은 반환하지 않는다.
7. LLM은 후보가 다소 부정확할 수 있음을 전제로 필요한 경로를 `query read`로 연다.

정밀도를 높이려고 상위 3개나 정확 일치만 반환하는 방식은 채택하지 않는다. 이 검색의 기준은 첫 결과의 정확도가 아니라 관련 문서가 후보 12개 안에 들어오는지다. 정확 용어, 이명, 코드 경로, 한국어 복합어 질의를 각각 5개 이상 평가해 `Recall@12`를 측정한다.

## 폴백

- 임베딩을 사용하지 않으면 메타데이터·키워드·관계 검색으로 진행하며 이 경우에도 위치만 반환한다.
- 임베딩을 사용하도록 설정했지만 SQLite 색인이 없으면 검색 시 자동으로 쓰지 않고, 승인된 `manage reindex --apply`를 요구한다.
- model ID 또는 vector 차원이 다르면 색인을 사용하지 않고 재색인을 요구한다.
- 일부 청크가 실패하면 실패한 문서 ID를 보고한다.
- 색인이 없거나 낡아도 원본 탐색과 정적 검증은 계속한다.
