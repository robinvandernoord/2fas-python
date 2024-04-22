export type AnyDict = { [key: string]: any };

export type TotpEntry = {
  service: string;
  username: string | null;
  // code: string;
  image?: string | null;
  icon_id: string;
  idx?: number | string; // not a real id but the index in the list of services
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

export interface TwoFasSettings {
  files: string[] | null;
  default_file: string | null;
  auto_verbose: boolean;
}

export interface TPython {
  // functions (here for typing only):
  load_image: (_: string) => Promise<string>;
  hello: () => null; // noop
  get_services: () => Promise<TwoFactorAuthDetails[]>;
  get_service: (idx: string | number) => Promise<TwoFactorAuthDetails>;
  get_settings: () => Promise<TwoFasSettings>;
  totp: (secret: string, delta_sec?: number | string) => Promise<string>;
}

export type AnyFunc = (..._: any[]) => any;

export interface Eel {
  expose: (_: AnyFunc, name?: string) => void;
}
