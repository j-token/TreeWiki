# 조회와 관리 명령

## 조회 명령

`query search`, `query read`, `query list`, `query graph`는 파일을 변경하지 않는다. 모든 조회는 `--principal`, `--team`, `--agent`, `--role`로 전달된 주체에 ACL을 먼저 적용한다.

## 관리 명령

`manage validate`는 읽기 전용이다. `manage sync`, `manage reindex`, `manage migrate`는 호출 주체가 `access_control.managers`에 있어야 하며, 기본적으로 계획만 출력하고 `--apply`가 있을 때만 파일을 변경한다.

에이전트는 사용자에게 파일 변경 허락을 받은 뒤에만 `--apply`를 전달한다. 조회 요청을 관리 요청으로 확대하지 않는다.
