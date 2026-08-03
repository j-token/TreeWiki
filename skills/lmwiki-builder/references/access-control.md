# 접근 제어

## 의미

```yaml
access:
  visibility: restricted
  owner: user:j-token
  team: team:repository
  grants:
    - subject: agent:builder
      permissions:
        - read
```

| visibility | 조회 조건 |
| --- | --- |
| `private` | `owner`만 조회 |
| `team` | 같은 `team` 주체가 조회 |
| `restricted` | `owner` 또는 `read` grant가 조회 |
| `agent` | `owner` 또는 지정된 `agent:*` grant가 조회 |

주체는 `user:*`, `role:*`, `agent:*`, `team:*` 형식을 사용한다. `owner`는 `user:*`, `team`은 `team:*`를 사용한다. 권한은 `read`, `write`, `manage`만 허용한다.

- 문서 편집은 owner 또는 `write` grant가 있는 주체만 수행한다.
- 접근 정책과 생명주기 변경은 owner 또는 `manage` grant가 있는 주체만 수행한다.
- 저장소 관리 명령은 `.knowledge/config.yml`의 `access_control.managers` 주체만 실행한다.

## 보안 경계

frontmatter ACL과 조회 CLI는 에이전트가 문서를 컨텍스트에 넣지 않도록 거르는 협력적 정책이다. Git 저장소를 읽을 수 있는 사람의 파일 접근을 차단하지 못한다.

- `private`와 `restricted` 문서는 기본적으로 `.knowledge/private-memory/`에 두고 Git에서 제외한다.
- 공개·공유 Git에 비밀을 넣은 뒤 ACL 메타데이터만 붙이지 않는다.
- 실제 다중 사용자 강제 집행이 필요하면 인증된 외부 저장소에서 ACL을 적용한다.
- 조회는 권한 필터를 검색 점수 계산보다 먼저 적용한다.
