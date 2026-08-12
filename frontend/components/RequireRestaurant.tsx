"use client";

import Link from "next/link";
import { useCurrentRestaurant } from "@/lib/restaurant";

export function RequireRestaurant({ children }: { children: (restaurantId: string) => React.ReactNode }) {
  const { restaurantId } = useCurrentRestaurant();

  if (!restaurantId) {
    return (
      <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        No restaurant selected. Go to{" "}
        <Link href="/restaurants" className="font-medium underline">
          Restaurants
        </Link>{" "}
        and select one first.
      </div>
    );
  }

  return <>{children(restaurantId)}</>;
}
