import TOTP from "./totp";
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

function render_template(template_id: string, variables: AnyDict) {
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
  return tmp_container.firstElementChild ?? tmp_container; // contents OR empty div
}

const $totp_holder = document.getElementById("totp-holder") as HTMLDivElement;

function new_totp_entry(data: TotpEntry, secret: string) {
  const entry = render_template("totp-entry", data);
  $totp_holder.appendChild(entry);

  const $code_holder = entry.querySelector(".entry-code");
  if (!$code_holder) {
    // will probably not happen
    return;
  }
  setIntervalImmediately(async () => {
    const code = await TOTP.generateOTP(secret, { format: true });
    $code_holder.innerHTML = code;
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

async function main() {
  // todo: check password/auth
  setIntervalImmediately(update_countdown, 1000);

  const services = await Python.get_services(/* password */);

  services.forEach(async (service) => {
    const image = await Python.load_image(service.icon.iconCollection.id);

    new_totp_entry(
      {
        service: service.name,
        username: "",
        code: "", // to be filled in a loop
        image,
      },
      service.secret,
    );
  });
}

main();
