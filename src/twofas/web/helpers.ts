import type {
  AnyDict,
  TwoFactorAuthDetails,
  TotpEntry,
  TPython,
  Eel,
} from "./_types";

declare var Python: TPython;
declare var eel: Eel;

/**
 * Like setInterval but with an invocation at t=0 as well
 */
export function setIntervalImmediately(
  func: () => any,
  interval: number,
): number {
  func();
  return setInterval(func, interval);
}

export function render_template(
  template_id: string,
  variables: AnyDict,
): HTMLElement {
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

export async function auth_details_to_totp_entry(
  idx: number | string,
  service: TwoFactorAuthDetails,
): Promise<TotpEntry> {
  const image = await Python.load_image(service.icon.iconCollection.id);

  return {
    icon_id: service.icon.iconCollection.id,
    service: service.name,
    username: service.otp.account ?? service.otp.label ?? "",
    idx, // not a real ID but idx in the list of services
    image,
  };
}

export function current_countdown_value() {
  return 30 - (Math.round(new Date().getTime() / 1000) % 30);
}

export function totp_format(code: string): string {
  return code.match(/.{1,3}/g)?.join(" ") ?? code;
}

export function copy_current_code($code_holder: HTMLDivElement) {
  const current_code = $code_holder.dataset.code;
  if (current_code) {
    navigator.clipboard.writeText(current_code);
  } else {
    console.error("No current code?");
  }
}
