set -e

su6 fix &
./prettier.sh

pushd src/twofas/web
  bunx tsc --noEmit
  # bunx tsc app.ts
  bun build app.ts --outfile app.js
  bun build entry.ts --outfile entry.js
  bun build login.ts --outfile login.js
popd

pip install .[gui]
2fas --gui
