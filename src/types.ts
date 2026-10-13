/** Domain shapes shared by services, routes and views. */

export type User = { email: string; name: string; isAdmin: boolean };

export type AssetType = { id: number; name: string; sort_order: number };

export type Asset = {
  id: number;
  name: string;
  type_id: number;
  type: { id: number; name: string };
  serial: string;
  chip_mounted: string;
  location: string;
  notes: string;
  retired: boolean;
  created_at: string;
};

export type Checkout = {
  id: number;
  asset_id: number;
  user_email: string;
  user_name: string;
  checked_out_at: string;
  returned_at: string | null;
  returned_by: string | null;
  notes: string;
  active: boolean;
  asset?: { id: number; name: string; type?: { id: number; name: string } };
};

export type FpgaType = { id: number; name: string };
export type FpgaServer = { id: number; name: string; notes: string };

/** key is `${fpga_type_id}:${server_id}` */
export type Placements = Map<string, number>;

export type FpgaReservation = {
  id: number;
  fpga_type_id: number;
  fpga_type: { id: number; name: string };
  server_id: number | null;
  server: { id: number; name: string } | null;
  project: string;
  quantity: number;
  contact: string;
  special_requests: string;
  start_date: string; // YYYY-MM-DD
  end_date: string; // YYYY-MM-DD
  created_by_email: string;
  created_at: string;
};

export type Bar = {
  reservation: FpgaReservation;
  left_pct: number;
  width_pct: number;
  over: boolean;
  hue: number | null;
};

export type TimelineRow = {
  label: string;
  hue: number | null;
  over_row: boolean;
  bars: Bar[];
};

export type TimelineGroup = {
  fpga_type: FpgaType;
  rows: TimelineRow[];
  installed: Array<[FpgaServer, number]>;
  total: number;
};

export type Timeline = {
  groups: TimelineGroup[];
  ticks: Array<{ label: string; left_pct: number }>;
  today_pct: number | null;
  warnings: string[];
};

/** Thrown by services; routes turn these into a status code and a message. */
export class ServiceError extends Error {
  readonly status: number = 400;
}
export class Conflict extends ServiceError {
  override readonly status = 409;
}
export class Forbidden extends ServiceError {
  override readonly status = 403;
}
