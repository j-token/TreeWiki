# 조회와 관리 명령

## 조회 명령

`query search`, `query read`, `query list`, `query graph`, `query glossary`, `query l3-candidates`는 파일을 변경하지 않는다. 모든 조회는 `--principal`, `--team`, `--agent`, `--role`로 전달된 주체에 ACL을 먼저 적용한다. `query l3-candidates`는 접근 가능한 활성 L1/L2를 subject별로 세고, 기존 L3가 이미 포괄한 근거를 제외한다.

## 관리 명령

`manage validate`는 읽기 전용이다. `manage sync`, `manage reindex`, `manage migrate`는 호출 주체가 `access_control.managers`에 있어야 하며, 기본적으로 계획만 출력하고 `--apply`가 있을 때만 파일을 변경한다.

에이전트는 사용자에게 파일 변경 허락을 받은 뒤에만 `--apply`를 전달한다. 조회 요청을 관리 요청으로 확대하지 않는다.

`manage migrate`는 현재 저장소 설정 버전과 스킬이 지원하는 목표 버전을 먼저 출력한다. 드라이런에서 설정 키·폴더·지원 파일 변경을 검토하고, 승인 뒤 같은 명령에 `--apply`를 추가한다. 더 최신 버전의 저장소 설정을 구버전 스킬로 내리지 않는다.

새 스킬 변경을 저장소의 `.agents/skills/lmwiki` 복사본에 반영하려면 새 스킬에 포함된 CLI로 `manage migrate ... --sync-skill-copy`를 실행한다. 이 옵션도 드라이런이 기본이며 `--apply` 전에는 파일을 바꾸지 않는다. 제거된 파일은 자동 삭제하지 않고 `skills-lock.json`도 수정하지 않는다. 잠금 파일은 원래 스킬 설치 관리자로 갱신한다.
