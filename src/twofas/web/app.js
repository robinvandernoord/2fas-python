// totp.ts
class TOTP {
  static generateOTP(secret, options) {
    const { period = 30, digits = 6, format = false } = options || {};
    const epoch = Math.floor(Date.now() / 1000);
    const counter = Math.floor(epoch / period);
    const counterBytes = this.intToBytes(counter);
    const secretBytes = this.stringToBytes(secret);
    const hmac = window.crypto.subtle.importKey("raw", secretBytes, { name: "HMAC", hash: "SHA-1" }, false, [
      "sign"
    ]).then((key) => window.crypto.subtle.sign("HMAC", key, new Uint8Array(counterBytes)));
    return hmac.then((hmacBytes) => {
      const offset = hmacBytes.byteLength - 1;
      const truncated = new DataView(hmacBytes).getUint32(offset - 3) & 2147483647;
      const pinValue = (truncated % Math.pow(10, digits)).toString().padStart(digits, "0");
      const formatted = pinValue.match(/.{1,3}/g)?.join(" ");
      return format && formatted ? formatted : pinValue;
    }).catch((error) => {
      console.error("Error generating OTP:", error);
      return "";
    });
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
var new_totp_entry = function(data) {
  const entry = render_template("totp-entry", data);
  $totp_holder.appendChild(entry);
};
var new_image = function(b64) {
  const $image = new Image;
  $image.src = b64;
  return $image;
};
var new_row = function($image) {
  const $row = document.createElement("div");
  $row.appendChild($image);
  return $row;
};
var to_holder = function($row) {
  return $imageholder.appendChild($row);
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
    Python.load_image("fff32440-f5be-4b9c-b471-f37d421f10c3").then(new_image).then(new_row).then(to_holder);
    Python.load_image("708df726-fb8b-4c01-8990-f2da0cd33839").then(new_image).then(new_row).then(to_holder);
  }
}
async function main() {
  const services = await Python.get_services();
  services.forEach(async (service) => {
    const code = await TOTP.generateOTP(service.secret, { format: true });
    const image = await Python.load_image(service.icon.iconCollection.id);
    new_totp_entry({
      service: service.name,
      username: "",
      code,
      image
    });
  });
}
var $totp_holder = document.getElementById("totp-holder");
var $imageholder = document.getElementById("imageholder");
eel.expose(hello);
eel.expose(python_task_started);
eel.expose(python_task_completed, "python_task_completed");
main();
