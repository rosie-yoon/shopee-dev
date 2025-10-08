# scripts/rollback_version.sh
#!/usr/bin/env bash
set -euo pipefail

ver="${1:-}"
if [[ -z "$ver" ]]; then
  echo "Usage: $0 vX.Y[.Z]"
  exit 1
fi

git fetch --all --tags

if git rev-parse -q --verify "refs/tags/$ver" >/dev/null; then
  echo "✅ Tag '$ver' found. Checking out..."
else
  echo "❌ Tag '$ver' not found. Did you push it? (git push origin $ver)"
  exit 2
fi

# 태그로부터 새 'pinned' 브랜치를 만들어 체크아웃 (detached HEAD 회피)
git checkout -B "pinned/$ver" "$ver"
echo "✅ Switched to branch 'pinned/$ver' at tag $ver."
echo "👉 배포/실행은 지금 워킹트리 기준으로 진행하세요."
