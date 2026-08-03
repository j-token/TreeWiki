# 조회와 관리 명령

## 조회

`query search`, `query read`, `query list`, `query graph`는 파일을 변경하지 않는다. `--principal`, `--team`, `--agent`, `--role`을 받아 ACL을 먼저 적용한다.

## 관리

`manage validate`는 읽기 전용이다. `manage sync`, `manage reindex`, `manage migrate`는 호출 주체가 `access_control.managers`에 있어야 하며 `--apply`가 없으면 계획만 출력한다.

에이전트는 사용자가 파일 변경을 허락한 뒤에만 `--apply`를 전달한다. 조회 요청을 관리 작업으로 확대하지 않는다.
