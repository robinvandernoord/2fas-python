// totp.ts
class TOTP {
  static async generateOTP(secret, {
    period = 30,
    digits = 6,
    format = false
  } = {}) {
    const epoch = Math.floor(Date.now() / 1000);
    const counter = Math.floor(epoch / period);
    const counterBytes = this.intToBytes(counter);
    const secretBytes = this.stringToBytes(secret);
    try {
      const key = await window.crypto.subtle.importKey("raw", secretBytes, { name: "HMAC", hash: "SHA-1" }, false, ["sign"]);
      const hmacBytes = await window.crypto.subtle.sign("HMAC", key, new Uint8Array(counterBytes));
      const offset = hmacBytes.byteLength - 1;
      const truncated = new DataView(hmacBytes).getUint32(offset - 3) & 2147483647;
      const pinValue = (truncated % Math.pow(10, digits)).toString().padStart(digits, "0");
      const formatted = pinValue.match(/.{1,3}/g)?.join(" ");
      return format && formatted ? formatted : pinValue;
    } catch (error) {
      console.error("Error generating OTP:", error);
      return "";
    }
  }
  static intToBytes(num) {
    const arr = new ArrayBuffer(8);
    const view = new DataView(arr);
    view.setBigUint64(0, BigInt(num), false);
    return new Uint8Array(arr);
  }
  static stringToBytes(str) {
    return new TextEncoder().encode(str);
  }
}

// app.ts
var setIntervalImmediately = function(func, interval) {
  func();
  return setInterval(func, interval);
};
var render_template = function(template_id, variables) {
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
};
var new_totp_entry = function(data, secret) {
  const entry = render_template("totp-entry", data);
  $totp_holder.appendChild(entry);
  const $code_holder = entry.querySelector(".entry-code");
  if (!$code_holder) {
    return;
  }
  setIntervalImmediately(async () => {
    const code = await TOTP.generateOTP(secret, { format: true });
    $code_holder.innerHTML = code;
  }, 1000);
};
var hello = function() {
  console.debug("Python says hello!");
  Python.hello();
};
var python_task_started = function(task) {
  console.debug(`${task} started in Python.`);
};
async function python_task_completed(task) {
  console.debug(`${task} completed in Python.`);
  if (task === "load_icons") {
  }
}
var current_countdown_value = function() {
  return 30 - Math.round(new Date().getTime() / 1000) % 30;
};
var update_countdown = function() {
  const value = String(current_countdown_value());
  document.querySelectorAll(".counter-circle").forEach(($counter) => {
    $counter.innerHTML = value;
  });
};
async function main() {
  setIntervalImmediately(update_countdown, 1000);
  const services = await Python.get_services();
  services.forEach(async (service) => {
    const image = await Python.load_image(service.icon.iconCollection.id);
    new_totp_entry({
      service: service.name,
      username: "",
      code: "",
      image
    }, service.secret);
  });
}
var $totp_holder = document.getElementById("totp-holder");
eel.expose(hello);
eel.expose(python_task_started);
eel.expose(python_task_completed, "python_task_completed");
main();
