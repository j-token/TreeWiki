# 문서 생명주기와 관계

## 상태

```text
draft -> active -> deprecated -> archived
          |                         ^
          +-------------------------+
deprecated -> active  # 재검토 후 복구
```

- `draft`: 기본 탐색에서 권위 있는 기준으로 사용하지 않는다.
- `active`: 현재 기준이며 기본 검색 대상이다.
- `deprecated`: 새 사용을 중단하지만 대체·과거 판단 추적을 위해 남긴다.
- `archived`: 기본 검색과 LLM 읽기 집합에서 제외한다.

삭제보다 상태 전이와 대체 관계를 사용한다. `active` 문서가 `deprecated` 또는 `archived` 문서에 `depends_on`하면 오류다. 과거 설명을 위한 `related_to`는 허용한다.

## 관계

| 관계 | 대상 | 의미 |
| --- | --- | --- |
| `derived_from` | 문서 ID | 결정이나 상위 계약에서 파생됨 |
| `depends_on` | 문서 ID | 대상 계약이 먼저 유효해야 함 |
| `supersedes` | 문서 ID | 대상 문서를 대체함 |
| `verified_by` | 파일 경로 또는 `command:` 값 | 계약 검증 근거 |
| `implemented_by` | 코드 경로 | 계약 구현 위치 |
| `related_to` | 문서 ID | 직접 의존하지 않는 관련 자료 |

관계는 현재 문서를 주어로 읽는다. 활성 계약에는 한 개 이상의 `verified_by`가 있어야 한다.

## 대체 절차

1. 새 문서를 새 ID와 `draft` 상태로 만든다.
2. 새 문서에 이전 문서를 가리키는 `supersedes`를 추가한다.
3. 검증 근거를 연결하고 새 문서를 `active`로 바꾼다.
4. 이전 문서를 `deprecated`로 바꾼다.
5. 지도와 활성 문서의 링크를 새 문서로 갱신한다.
6. 검증기를 실행한다.
