---
id: MAP-ROOT-001
type: map
---

# TreeWiki 프로젝트 지도

TreeWiki 0.3.0은 프로젝트의 정책과 결정사항을 짧은 Markdown으로 기록하고, 사람과 코딩 에이전트가 필요한 문서만 점진적으로 찾도록 돕는 로컬 우선 플러그인입니다.

복잡한 문서 관리 체계 대신 저장소 지도, 표준 Markdown 링크와 인용, SQLite BM25 검색, 로컬 변경 이력을 조합합니다. 외부 인용은 링크로만 보존하며 자동으로 가져오거나 캐시하지 않습니다.

## 동작 방식

1. 가장 가까운 `AGENTS.md`에서 프로젝트와 하위 문서의 진입점을 찾습니다.
2. BM25 검색은 관련 문서의 위치와 링크로 연결된 이웃 문서를 반환합니다.
3. 선택한 정책이나 결정만 읽고, 필요한 경우 짧은 문서로 수정하거나 추가합니다.
4. 검증 후 `.knowledge/document-history/`에 의미 변화만 기록하고 `.knowledge/index/`의 파생 색인을 갱신합니다.

## 프로젝트 구성

- [Agent Plugin](plugins/treewiki/README.md): 스킬, Python 코어, 6개 MCP 도구, 템플릿과 테스트의 canonical 원본입니다.
- [Claude Plugin](plugins/treewiki-claude/README.md): Agent Plugin의 스킬과 런타임에서 생성되는 `/treewiki` 플러그인입니다.
- [정책 지도](docs/policies/AGENTS.md): 프로젝트가 지속적으로 따라야 하는 규칙을 연결합니다.
- [결정 지도](docs/decisions/AGENTS.md): 선택의 배경, 결과와 트레이드오프를 연결합니다.

TreeWiki는 독립 스킬로 배포하지 않습니다. Agent Plugin을 먼저 수정하고 Claude 런타임 생성물은 직접 편집하지 않습니다.

## 문서 모델

- 관리 유형은 `map`, `policy`, `decision`입니다.
- frontmatter에는 안정적인 `id`와 `type`만 둡니다.
- 제목은 첫 H1, 관계는 상대 Markdown 링크, 인용은 `## Sources`에서 파생합니다.
- 본문은 가능하면 50줄 이내로 유지하며 초과는 오류가 아닌 검토 경고입니다.

## 개발과 검증

관련 없는 dirty-tree 작업은 보존하고 다음 검사를 실행합니다.

```powershell
Push-Location plugins/treewiki
npm run check
Pop-Location
python plugins/treewiki/skills/treewiki/scripts/treewiki_cli.py validate .
python plugins/treewiki/skills/treewiki/scripts/treewiki_cli.py sync .
```
