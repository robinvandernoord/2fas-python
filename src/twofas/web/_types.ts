export type TotpEntry = {
  service: string;
  username: string | null;
  // code: string;
  image?: string | null;
  icon_id: string;
};

export interface OtpDetails {
  link: string;
  tokenType: string;
  source: string;
  label?: string | null;
  account?: string | null;
  digits?: number | null;
  period?: number | null;
}

export interface OrderDetails {
  position: number;
}

export interface IconCollectionDetails {
  id: string;
}

export interface IconDetails {
  selected: string;
  iconCollection: IconCollectionDetails;
}

export interface TwoFactorAuthDetails {
  name: string;
  secret: string;
  updatedAt: number;
  serviceTypeID?: string | null;
  otp: OtpDetails;
  order: OrderDetails;
  icon: IconDetails;
  groupId?: string | null;
}
export interface TPython {
  // functions (here for typing only):
  load_image: (_: string) => Promise<string>;
  hello: () => null; // noop
  get_services: () => Promise<TwoFactorAuthDetails[]>;
  totp: (secret: string) => Promise<string>;
}

export type AnyFunc = (..._: any[]) => any;

export interface Eel {
  expose: (_: AnyFunc, name?: string) => void;
}
