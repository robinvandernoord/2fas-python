// thanks ChatGPT

export default class TOTP {
  static async generateOTP(
    secret: string,
    {
      period = 30,
      digits = 6,
      format = false,
    }: {
      period?: number;
      digits?: number;
      format?: boolean;
    } = {},
  ): Promise<string> {
    const epoch = Math.floor(Date.now() / 1000);
    const counter = Math.floor(epoch / period);
    const counterBytes = this.intToBytes(counter);
    const secretBytes = this.stringToBytes(secret);

    try {
      const key = await window.crypto.subtle.importKey(
        "raw",
        secretBytes,
        { name: "HMAC", hash: "SHA-1" },
        false,
        ["sign"],
      );

      const hmacBytes = await window.crypto.subtle.sign(
        "HMAC",
        key,
        new Uint8Array(counterBytes),
      );

      const offset = hmacBytes.byteLength - 1;
      const truncated =
        new DataView(hmacBytes).getUint32(offset - 3) & 0x7fffffff;
      const pinValue = (truncated % Math.pow(10, digits))
        .toString()
        .padStart(digits, "0");
      const formatted = pinValue.match(/.{1,3}/g)?.join(" ");

      return format && formatted ? formatted : pinValue;
    } catch (error) {
      console.error("Error generating OTP:", error);
      return "";
    }
  }

  private static intToBytes(num: number): Uint8Array {
    const arr = new ArrayBuffer(8); // Assuming 64-bit counter
    const view = new DataView(arr);
    view.setBigUint64(0, BigInt(num), false);
    return new Uint8Array(arr);
  }

  private static stringToBytes(str: string): Uint8Array {
    return new TextEncoder().encode(str);
  }
}
