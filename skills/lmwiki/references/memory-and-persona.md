# 기억 계층과 Persona

## 계층

| 계층 | 내용 | 기본 보관 위치 | 기본 임베딩 |
| --- | --- | --- | --- |
| `l0` | 원문 대화와 도구 실행 기록 | `.knowledge/private-memory/l0/` | `deny` |
| `l1` | 한 가지 사실, 선호, 제약 또는 사건 | `.knowledge/private-memory/l1/` | `local_only` |
| `l2` | 프로젝트·업무 장면별 작업 맥락 | `.knowledge/private-memory/l2/` 또는 `docs/memory/l2/` | `local_only` |
| `l3` | 오래 유지되는 Persona와 협업 방식 | `.knowledge/private-memory/l3/` | `local_only` |

L1 이상은 `distilled_from` 관계로 이전 계층의 문서 ID를 가리킨다. 원문을 확인할 수 없는 추론은 `confidence`를 낮추고 본문에 근거와 반증 조건을 남긴다.

## 수명

- L0는 원문이므로 수정하지 않고 새 기록을 추가한다.
- L1은 원문과 충돌하면 대체 문서를 만들고 `supersedes`를 기록한다.
- L2는 특정 프로젝트나 기간이 끝나면 `deprecated`로 전환할 수 있다.
- L3 Persona는 단일 대화로 갱신하지 않는다. 서로 다른 L1 또는 L2 근거를 두 개 이상 확인한다.
- Persona는 사용자의 정체성을 단정하지 않고 에이전트가 적용할 협업 선호와 안정적인 제약만 기록한다.

## 저장 경계

공개 또는 팀 Git 저장소에 개인 대화 원문과 Persona를 기본 저장하지 않는다. 공유가 명시된 L2만 `docs/memory/`에 둘 수 있다. 민감 정보, 비밀, 인증 정보와 제3자 개인정보는 기억으로 승격하지 않는다.
