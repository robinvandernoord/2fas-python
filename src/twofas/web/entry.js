// helpers.ts
function setIntervalImmediately(func, interval) {
  func();
  return setInterval(func, interval);
}
function render_template(template_id, variables) {
  const template = document.getElementById(template_id);
  if (!template) {
    throw `Template ${template} not found.`;
  }
  let content = template.innerHTML;
  content = content.replace(/\${(.*?)}/g, (_, variable) => {
    return variables[variable.trim()] ?? "";
  });
  const tmp_container = document.createElement("div");
  tmp_container.innerHTML = content;
  return tmp_container.firstElementChild ?? tmp_container;
}
async function auth_details_to_totp_entry(idx, service) {
  const image = await Python.load_image(service.icon.iconCollection.id);
  return {
    icon_id: service.icon.iconCollection.id,
    service: service.name,
    username: service.otp.account ?? service.otp.label ?? "",
    idx,
    image
  };
}
function current_countdown_value() {
  return 30 - Math.round(new Date().getTime() / 1000) % 30;
}
function totp_format(code) {
  return code.match(/.{1,3}/g)?.join(" ") ?? code;
}
function copy_current_code($code_holder) {
  const current_code = $code_holder.dataset.code;
  if (current_code) {
    navigator.clipboard.writeText(current_code);
  } else {
    console.error("No current code?");
  }
}

// entry.ts
async function load_details(idx) {
  const details = await Python.get_service(idx);
  const entry = await auth_details_to_totp_entry(idx, details);
  const $entry = render_template("entry-details-template", entry);
  $holder.appendChild($entry);
  const $$code_holders = $entry.querySelectorAll(".totp-code");
  $$code_holders.forEach(($totp) => {
    setIntervalImmediately(() => {
      Python.totp(details.secret, $totp.dataset.delta).then((code) => {
        $totp.innerHTML = totp_format(code);
        $totp.dataset.code = code;
      });
    }, 1000);
    $totp.addEventListener("click", (_) => {
      copy_current_code($totp);
    });
  });
}
async function main() {
  const $tmp = document.getElementById("tmp");
  const _data = new URLSearchParams(window.location.search);
  const data = Object.fromEntries(_data);
  await load_details(data.idx);
  setIntervalImmediately(() => {
    $countdown.innerHTML = String(current_countdown_value());
  }, 1000);
}
var $holder = document.getElementById("entry-details");
var $countdown = document.getElementById("counter-circle");
main();
