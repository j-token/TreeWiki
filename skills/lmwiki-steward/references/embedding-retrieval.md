# 선택적 임베딩 검색

이 문서는 `.knowledge/config.yml`의 `embedding.enabled`가 `true`일 때만 읽는다.

## 안전 경계

- Markdown과 frontmatter를 권위 있는 원본으로 유지한다.
- 벡터 저장소는 삭제 후 재생성 가능한 파생 색인으로 취급한다.
- 사용자가 허용하지 않으면 문서를 외부 API로 전송하지 않는다.
- `embedding.mode: local_only` 문서는 원격 provider로 보내지 않는다.
- `embedding.mode: deny` 문서는 청크도 만들지 않는다.
- 원격 provider 장애 시 다른 provider로 자동 전환하지 않는다.

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

`scripts/build_embedding_index.py`는 provider 중립 JSONL manifest를 만든다. 실제 벡터 계산은 저장소에서 확인한 provider adapter로 수행한다.

## 검색

1. `status`, `authority`, `applies_to`로 필터링한다.
2. 통제어휘의 표준 키와 이명을 확장한다.
3. 필터 안에서 상위 12개 청크를 검색한다.
4. 같은 문서 청크를 합쳐 최대 6개 문서로 줄인다.
5. `map`과 `contract`를 정보 문서보다 우선한다.
6. 문서 관계를 최대 8개까지 확장한다.
7. 문서 ID, 헤딩과 선택 이유를 결과에 남긴다.

수치는 초기값이다. 정확 용어, 이명, 코드 경로를 포함한 질의를 각각 5개 이상 평가하고 기대 문서가 최종 6개 안에 포함되는 `Recall@6`를 측정한다. 초기 목표는 90%다. 메타데이터 전용 검색보다 낮으면 임베딩을 기본 검색으로 사용하지 않는다.

## 폴백

- provider나 vector store를 사용할 수 없으면 메타데이터·키워드·관계 검색으로 진행한다.
- model ID 또는 vector 차원이 다르면 색인을 사용하지 않고 재색인을 요구한다.
- 일부 청크가 실패하면 실패한 문서 ID를 보고한다.
- 색인이 없거나 낡아도 원본 탐색과 정적 검증은 계속한다.
