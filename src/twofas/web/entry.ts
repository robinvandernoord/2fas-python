import { TPython, Eel, TotpEntry } from "./_types";
import {
  render_template,
  auth_details_to_totp_entry,
  setIntervalImmediately,
  current_countdown_value,
  totp_format,
  copy_current_code,
} from "./helpers";

declare var Python: TPython;
declare var eel: Eel;

const $holder = document.getElementById("entry-details") as HTMLElement;

async function load_details(idx: string) {
  const details = await Python.get_service(idx);

  const entry = await auth_details_to_totp_entry(idx, details);

  const $entry = render_template("entry-details-template", entry);

  $holder.appendChild($entry);

  // prev, current, next:

  const $$code_holders = $entry.querySelectorAll(
    ".totp-code",
  ) as NodeListOf<HTMLDivElement>;

  $$code_holders.forEach(($totp) => {
    setIntervalImmediately(() => {
      Python.totp(details.secret, $totp.dataset.delta).then((code) => {
        $totp.innerHTML = totp_format(code);
        $totp.dataset.code = code;
      });
    }, 1_000);

    $totp.addEventListener("click", (_) => {
      copy_current_code($totp);
    });
  });
}

const $countdown = document.getElementById("counter-circle") as HTMLDivElement;

async function main() {
  const $tmp = document.getElementById("tmp") as HTMLDivElement;
  const _data = new URLSearchParams(window.location.search) as any as Map<
    string,
    string
  >; // weird TS
  const data = Object.fromEntries(_data);

  await load_details(data.idx);

  // countdown
  setIntervalImmediately(() => {
    $countdown.innerHTML = String(current_countdown_value());
  }, 1000);
}

main();
