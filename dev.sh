set -e

su6 fix &
./prettier.sh

pushd src/twofas/web
  bunx tsc --noEmit
  # bunx tsc app.ts
  bun build app.ts --outfile app.js
popd

pip install .[gui]
2fas --gui
