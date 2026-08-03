# 기억 계층과 Persona

| 계층 | 내용 | 기본 보관 위치 | 기본 임베딩 |
| --- | --- | --- | --- |
| `l0` | 원문 대화와 도구 실행 기록 | `.knowledge/private-memory/l0/` | `deny` |
| `l1` | 한 가지 사실, 선호, 제약 또는 사건 | `.knowledge/private-memory/l1/` | `local_only` |
| `l2` | 프로젝트·업무 장면별 작업 맥락 | 로컬 또는 `docs/memory/l2/` | `local_only` |
| `l3` | 오래 유지되는 Persona와 협업 방식 | `.knowledge/private-memory/l3/` | `local_only` |

L1 이상은 `distilled_from` 관계로 이전 계층의 문서 ID를 가리킨다. L0는 수정하지 않고 새 기록을 추가한다. L3 Persona는 서로 다른 L1 또는 L2 근거를 두 개 이상 확인한 뒤 갱신한다.

Persona에는 에이전트가 적용할 협업 선호와 안정적인 제약만 기록한다. 민감 정보, 비밀, 인증 정보, 제3자 개인정보와 근거 없는 성격 추론은 승격하지 않는다.
