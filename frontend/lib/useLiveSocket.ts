"use client";

import { useEffect, useRef } from "react";
import { apiFetch } from "./api";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";

function wsUrl(restaurantId: string, token: string, deviceToken?: string): string {
  const wsBase = API_BASE_URL.replace(/^http/, "ws");
  const param = deviceToken ? `device_token=${encodeURIComponent(deviceToken)}` : `token=${encodeURIComponent(token)}`;
  return `${wsBase}/ws/restaurants/${restaurantId}/orders?${param}`;
}

export interface UseLiveSocketOptions {
  /**
   * Raw POS display device token (see app/pos/[restaurantId]) instead of a staff
   * session. When set, the staff ws-ticket fetch below is skipped entirely -- the
   * unauthenticated /pos route has no staff session to mint a ticket from.
   */
  deviceToken?: string;
}

/**
 * Live order/handover/payment events for a restaurant, replacing Phase 1's polling.
 * Auto-reconnects with a fixed delay on close; the server-side ConnectionManager is
 * in-memory and single-process, so a reconnect just re-subscribes -- no state to replay.
 */
export function useLiveSocket(
  restaurantId: string | null,
  onEvent: (event: any) => void,
  options?: UseLiveSocketOptions
) {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const deviceToken = options?.deviceToken;

  useEffect(() => {
    if (!restaurantId) return;

    let socket: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;

    async function connect() {
      let ticket = "";
      if (!deviceToken) {
        // The session lives in an httpOnly cookie a WebSocket handshake can't carry as a
        // query param -- mint a short-lived, single-purpose ticket over the regular
        // (cookie-authenticated) API instead of ever exposing the real session token in a
        // URL. See backend app/api/v1/routers/auth.py::ws_ticket.
        try {
          const res = await apiFetch<{ ticket: string }>("/auth/ws-ticket");
          ticket = res.ticket;
        } catch {
          return; // Not signed in (or session expired) -- nothing to connect with.
        }
        if (stopped) return;
      }

      socket = new WebSocket(wsUrl(restaurantId!, ticket, deviceToken));
      socket.onmessage = (event) => {
        try {
          onEventRef.current(JSON.parse(event.data));
        } catch {
          // ignore malformed frames
        }
      };
      socket.onclose = () => {
        if (!stopped) reconnectTimer = setTimeout(connect, 3000);
      };
      socket.onerror = () => {
        socket?.close();
      };
    }

    connect();

    return () => {
      stopped = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [restaurantId, deviceToken]);
}
