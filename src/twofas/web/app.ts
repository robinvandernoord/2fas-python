import TOTP from "./totp";
import { TPython, Eel, TotpEntry } from "./_types";

declare var Python: TPython;
declare var eel: Eel;

type AnyDict = { [key: string]: any };

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

function new_totp_entry(data: TotpEntry) {
  const entry = render_template("totp-entry", data);
  $totp_holder.appendChild(entry);
}

function new_image(b64: string) {
  const $image = new Image();
  $image.src = b64;
  return $image;
}

function new_row($image: HTMLImageElement) {
  const $row = document.createElement("div");
  $row.appendChild($image);
  return $row;
}

const $imageholder = document.getElementById("imageholder") as HTMLDivElement;

function to_holder($row: HTMLDivElement) {
  return $imageholder.appendChild($row);
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
    // github icon
    Python.load_image("fff32440-f5be-4b9c-b471-f37d421f10c3")
      .then(new_image)
      .then(new_row)
      .then(to_holder);
    // wordpress icon
    Python.load_image("708df726-fb8b-4c01-8990-f2da0cd33839")
      .then(new_image)
      .then(new_row)
      .then(to_holder);
  }
}

eel.expose(python_task_completed, "python_task_completed");

// count down:
// setInterval(() => (console.log(30 - Math.round(new Date() / 1000) % 30)), 1000)

async function main() {
  // todo: check password/auth

  const services = await Python.get_services(/* password */);

  services.forEach(async (service) => {
    const code = await TOTP.generateOTP(service.secret, { format: true });

    const image = await Python.load_image(service.icon.iconCollection.id);

    new_totp_entry({
      service: service.name,
      username: "",
      code,
      image,
    });
  });
}

main();
