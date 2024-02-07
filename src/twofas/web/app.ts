import { TPython, Eel, TotpEntry } from "./_types";
import {
  auth_details_to_totp_entry,
  copy_current_code,
  current_countdown_value,
  render_template,
  setIntervalImmediately,
  totp_format,
} from "./helpers";

declare var Python: TPython;
declare var eel: Eel;

const $totp_holder = document.getElementById("totp-holder") as HTMLDivElement;

function new_totp_entry(data: TotpEntry, secret: string) {
  const entry = render_template("totp-entry", data);
  $totp_holder.appendChild(entry);

  // store all data:
  Object.assign(entry.dataset, {
    idx: data.idx,
    icon_id: data.icon_id,
    service: data.service.toLowerCase(),
    username: data.username?.toLowerCase() ?? "",
  });

  // todo: on click on service show more info, previous + next TOTP code

  const $code_holder = entry.querySelector(".entry-code") as HTMLDivElement;

  entry.addEventListener("click", (event) => {
    const idx = entry.dataset.idx;
    window.location.href = `entry.html?idx=${idx}`;
  });

  let t = 0; // timeout
  $code_holder.addEventListener("click", async (event) => {
    clearTimeout(t);
    // keep active for some longer:
    $code_holder.classList.add("active");
    t = setTimeout(() => {
      $code_holder.classList.remove("active");
    }, 1000);

    copy_current_code($code_holder);

    event.stopPropagation(); // no click on outer scope
  });

  setIntervalImmediately(async () => {
    const code = await Python.totp(secret);
    const formatted = totp_format(code);
    $code_holder.dataset.code = code;
    $code_holder.innerHTML = formatted;
  }, 1_000);
}

function fix_missing_icons() {
  const missing_imgs = document.querySelectorAll(
    '.totp-entry img[src=""]',
  ) as NodeListOf<HTMLImageElement>;

  if (missing_imgs.length) {
    console.debug(`Try to fix ${missing_imgs.length} images.`);
  } else {
    console.debug(`No missing images!`);
  }

  missing_imgs.forEach(async ($img) => {
    const icon_id = $img.dataset.icon;
    if (!icon_id) {
      return;
    }
    const img = await Python.load_image(icon_id);
    $img.src = img;
  });
}

function hello() {
  console.debug("Python says hello!");
  Python.hello();
}

eel.expose(hello);

function python_task_started(task: string) {
  console.debug(`${task} started in Python.`);
}

eel.expose(python_task_started);

async function python_task_completed(task: string) {
  console.debug(`${task} completed in Python.`);

  if (task === "load_icons") {
    // todo: check if any icons were missing
    fix_missing_icons();
  }
}

eel.expose(python_task_completed, "python_task_completed");

function update_countdown() {
  const value = String(current_countdown_value());

  document.querySelectorAll(".counter-circle").forEach(($counter) => {
    $counter.innerHTML = value;
  });
}

async function init_services() {
  const services = await Python.get_services(/* password */);

  const promises = services.map(async (service, idx) => {
    const entry = await auth_details_to_totp_entry(idx, service);

    new_totp_entry(entry, service.secret);

    return true;
  });

  // when services exist in dom, update backgrounds:
  Promise.all(promises).then(apply_alternating_background_colors);
}

function apply_alternating_background_colors() {
  const entries = document.querySelectorAll(
    ".totp-entry:not(.hidden)",
  ) as NodeListOf<HTMLElement>;

  entries.forEach(function (entry, index) {
    if (index % 2 === 0) {
      entry.style.backgroundColor = "var(--light-bg)";
    } else {
      entry.style.backgroundColor = "var(--dark-bg)";
    }
  });
}

const $search = document.getElementById("search") as HTMLInputElement;

function search(_: Event) {
  const query = $search.value.toLowerCase();

  const entries = document.querySelectorAll(
    ".totp-entry",
  ) as NodeListOf<HTMLElement>;

  entries.forEach((entry: HTMLElement) => {
    let matches =
      !query ||
      entry.dataset.service?.includes(query) ||
      entry.dataset.username?.includes(query);

    entry.classList.toggle("hidden", !matches);
  });

  // after toggling .hidden, update backgrounds:
  apply_alternating_background_colors();
}

async function setup_search() {
  $search.addEventListener("change", search);
  $search.addEventListener("keyup", search);

  // auto focus on typing anywhere in the window:
  document.addEventListener("keydown", (_) => {
    $search.focus();
  });
}

async function main() {
  // todo: check password/auth
  setIntervalImmediately(update_countdown, 1000);

  await init_services();
  await setup_search();
}

main();
