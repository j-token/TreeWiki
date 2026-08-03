# 접근 제어

```yaml
access:
  visibility: restricted
  owner: user:j-token
  team: team:repository
  grants:
    - subject: agent:builder
      permissions: [read]
```

- `private`: `owner`만 조회
- `team`: 같은 `team` 주체가 조회
- `restricted`: `owner` 또는 `read` grant가 조회
- `agent`: `owner` 또는 지정된 `agent:*` grant가 조회

주체는 `user:*`, `role:*`, `agent:*`, `team:*` 형식을 사용한다. `owner`는 `user:*`, `team`은 `team:*`를 사용한다. 권한은 `read`, `write`, `manage`만 허용하며 조회는 권한 필터를 검색 점수보다 먼저 적용한다.

- 문서 편집은 owner 또는 `write` grant가 있는 주체만 수행한다.
- 접근 정책과 생명주기 변경은 owner 또는 `manage` grant가 있는 주체만 수행한다.
- `manage sync/reindex/migrate`는 `access_control.managers`에 등록된 주체만 실행한다.

frontmatter ACL은 Git 파일 접근을 막지 못한다. `private`와 `restricted` 기억은 `.knowledge/private-memory/`에 두고 Git에서 제외한다. 실제 다중 사용자 강제 집행은 인증된 외부 저장소가 필요하다.
