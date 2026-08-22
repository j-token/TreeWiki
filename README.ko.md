# TreeWiki 0.3

[English](README.md)

TreeWiki는 프로젝트의 정책과 결정사항을 문서화하고 찾는 플러그인입니다. 관리 Markdown의 frontmatter에는 안정적인 `id`와 `type`만 두며 제목, 요약, 링크, backlink, 인용은 본문에서 파생합니다.

## 플러그인

- `plugins/treewiki`는 canonical Agent Plugin이자 Codex 호환 패키지입니다.
- `plugins/treewiki-claude`는 생성된 Claude Code `/treewiki` 경로를 제공합니다.
- 독립 TreeWiki 스킬은 배포하지 않습니다.

이 저장소의 marketplace에서 Agent Plugin을 설치하거나 Claude marketplace에서 Claude 플러그인을 설치할 수 있습니다. 두 패키지의 버전은 `0.3.0`입니다.

## 문서 모델

TreeWiki는 `AGENTS.md` 지도, `docs/policies/**/*.md`, `docs/decisions/**/*.md`를 관리합니다. 탐색에는 표준 Markdown 상대 링크를 사용하고 인용은 `## Sources` 아래에 둡니다. 본문이 50줄을 넘으면 경고합니다.

문서 이력은 `.knowledge/document-history/`에 로컬로 추가됩니다. SQLite FTS5/BM25 색인은 `.knowledge/index/`에 자동 재생성하며 외부 인용은 가져오거나 캐시하지 않습니다.

## 개발

```powershell
Push-Location plugins/treewiki
npm run check
npm run build:claude
Pop-Location
python -m unittest plugins.treewiki.tests.test_treewiki_v030 -v
```

[저장소 지도](AGENTS.md), [정책](docs/policies/AGENTS.md), [0.3 결정](docs/decisions/treewiki-0.3.md)을 참고하세요.
