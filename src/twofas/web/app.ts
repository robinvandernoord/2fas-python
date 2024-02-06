import { TPython, Eel, TotpEntry } from "./_types";

declare var Python: TPython;
declare var eel: Eel;

type AnyDict = { [key: string]: any };

/**
 * Like setInterval but with an invocation at t=0 as well
 */
function setIntervalImmediately(func: () => any, interval: number): number {
  func();
  return setInterval(func, interval);
}

function render_template(template_id: string, variables: AnyDict): HTMLElement {
  const template = document.getElementById(template_id);
  if (!template) {
    throw `Template ${template} not found.`;
  }

  // Get the template content
  let content = template.innerHTML;

  // Interpolate variables into template content
  content = content.replace(/\${(.*?)}/g, (_, variable: string) => {
    return variables[variable.trim()] ?? "";
  });

  // Create a temporary container to hold the parsed HTML
  const tmp_container = document.createElement("div");
  tmp_container.innerHTML = content;

  // Get the template content after interpolation
  return (tmp_container.firstElementChild ?? tmp_container) as HTMLElement;
  // contents OR empty div
}

const $totp_holder = document.getElementById("totp-holder") as HTMLDivElement;

function copy_current_code($code_holder: HTMLDivElement) {
  const current_code = $code_holder.dataset.code;
  if (current_code) {
    navigator.clipboard.writeText(current_code);
  } else {
    console.error("No current code?");
  }
}

function new_totp_entry(data: TotpEntry, secret: string) {
  const entry = render_template("totp-entry", data);
  $totp_holder.appendChild(entry);

  // store all data:
  Object.assign(entry.dataset, {
    service: data.service.toLowerCase(),
    username: data.username?.toLowerCase() ?? "",
  });

  const $code_holder = entry.querySelector(".entry-code") as HTMLDivElement;

  let t = 0; // timeout
  $code_holder.addEventListener("click", async (_) => {
    clearTimeout(t);
    // keep active for some longer:
    $code_holder.classList.add("active");
    t = setTimeout(() => {
      $code_holder.classList.remove("active");
    }, 1000);

    copy_current_code($code_holder);
  });

  setIntervalImmediately(async () => {
    const code = await Python.totp(secret);
    const formatted = code.match(/.{1,3}/g)?.join(" ") ?? code;
    $code_holder.dataset.code = code;
    $code_holder.innerHTML = formatted;
  }, 1_000);
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
  }
}

eel.expose(python_task_completed, "python_task_completed");

function current_countdown_value() {
  return 30 - (Math.round(new Date().getTime() / 1000) % 30);
}

function update_countdown() {
  const value = String(current_countdown_value());

  document.querySelectorAll(".counter-circle").forEach(($counter) => {
    $counter.innerHTML = value;
  });
}

async function init_services() {
  const services = await Python.get_services(/* password */);

  const promises = services.map(async (service) => {
    const image = await Python.load_image(service.icon.iconCollection.id);

    new_totp_entry(
      {
        service: service.name,
        username: service.otp.account ?? service.otp.label ?? "",
        image,
      },
      service.secret,
    );

    return true;
  });

  // when services exist in dom, update backgrounds:
  Promise.all(promises).then(apply_alternating_background_colors);
}

function apply_alternating_background_colors() {
  const entries = document.querySelectorAll(
    ".totp-entry:not(.hidden)",
  ) as NodeListOf<HTMLElement>;

  console.log("apply_alternating_background_colors", entries);

  entries.forEach(function (entry, index) {
    if (index % 2 === 0) {
      entry.style.backgroundColor = "var(--light-bg)";
    } else {
      entry.style.backgroundColor = "var(--dark-bg)";
    }
  });
}

const $search = document.getElementById("search") as HTMLInputElement;

function search(event: Event) {
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
