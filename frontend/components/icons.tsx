// Hand-authored line-icon set (Lucide-style: 24x24 viewBox, stroke-based) used in place
// of emoji throughout the admin UI. No external icon library dependency.
import type { SVGProps } from "react";

export interface IconProps extends Omit<SVGProps<SVGSVGElement>, "children"> {
  size?: number;
}

function Svg({ size = 18, strokeWidth = 1.75, className = "", ...props }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      {...props}
    />
  );
}

export const IconDashboard = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="3" width="7" height="9" rx="1.5" />
    <rect x="14" y="3" width="7" height="5" rx="1.5" />
    <rect x="14" y="12" width="7" height="9" rx="1.5" />
    <rect x="3" y="16" width="7" height="5" rx="1.5" />
  </Svg>
);

export const IconBuilding = (p: IconProps) => (
  <Svg {...p}>
    <rect x="4" y="3" width="16" height="18" rx="1.5" />
    <rect x="7.5" y="6.5" width="2.5" height="2.5" />
    <rect x="14" y="6.5" width="2.5" height="2.5" />
    <rect x="7.5" y="11.5" width="2.5" height="2.5" />
    <rect x="14" y="11.5" width="2.5" height="2.5" />
    <path d="M9.5 21v-4h5v4" />
  </Svg>
);

export const IconLayers = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3 3 8l9 5 9-5-9-5z" />
    <path d="M3 13l9 5 9-5" />
  </Svg>
);

export const IconGift = (p: IconProps) => (
  <Svg {...p}>
    <rect x="4" y="9" width="16" height="11" rx="1.5" />
    <path d="M4 9h16" />
    <path d="M12 9v11" />
    <path d="M12 9c-1.8 0-3.2-1.2-3.2-3S9.5 3.5 10.8 3.5 12 5.5 12 7v2z" />
    <path d="M12 9c1.8 0 3.2-1.2 3.2-3S13.5 3.5 12.2 3.5 12 5.5 12 7v2z" />
  </Svg>
);

export const IconMapPin = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 21s7-6.4 7-11.5A7 7 0 0 0 5 9.5C5 14.6 12 21 12 21z" />
    <circle cx="12" cy="9.5" r="2.3" />
  </Svg>
);

export const IconPackage = (p: IconProps) => (
  <Svg {...p}>
    <path d="M21 8 12 3 3 8v8l9 5 9-5V8z" />
    <path d="M3 8l9 5 9-5" />
    <path d="M12 13v8" />
  </Svg>
);

export const IconMessageSquare = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 4.5h16a1 1 0 0 1 1 1V15a1 1 0 0 1-1 1H9l-4 4v-4H4a1 1 0 0 1-1-1V5.5a1 1 0 0 1 1-1z" />
  </Svg>
);

export const IconBot = (p: IconProps) => (
  <Svg {...p}>
    <rect x="5" y="9" width="14" height="10" rx="2.5" />
    <circle cx="9.5" cy="14" r="1.1" fill="currentColor" stroke="none" />
    <circle cx="14.5" cy="14" r="1.1" fill="currentColor" stroke="none" />
    <path d="M12 9V5.5" />
    <circle cx="12" cy="4" r="1.3" />
    <path d="M2 13v2M22 13v2" />
  </Svg>
);

export const IconHome = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 11.5 12 4l8 7.5" />
    <path d="M6 10v9.5a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1V10" />
    <path d="M10 20.5V14h4v6.5" />
  </Svg>
);

export const IconWorkflow = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="4" width="6" height="4.5" rx="1.2" />
    <rect x="15" y="4" width="6" height="4.5" rx="1.2" />
    <rect x="9" y="16" width="6" height="4.5" rx="1.2" />
    <path d="M6 8.5v3a2 2 0 0 0 2 2h1.5" />
    <path d="M18 8.5v3a2 2 0 0 1-2 2h-1.5" />
    <path d="M12 13.5V16" />
  </Svg>
);

export const IconEye = (p: IconProps) => (
  <Svg {...p}>
    <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" />
    <circle cx="12" cy="12" r="3" />
  </Svg>
);

export const IconPlug = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 3v6M15 3v6" />
    <path d="M6 9h12v3a6 6 0 0 1-12 0V9z" />
    <path d="M12 18v3" />
  </Svg>
);

export const IconSend = (p: IconProps) => (
  <Svg {...p}>
    <path d="M22 2 11 13" />
    <path d="M22 2 15 22l-4-9-9-4 20-7z" />
  </Svg>
);

export const IconMegaphone = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 10v4a1 1 0 0 0 1 1h2l4.5 4V5L6 9H4a1 1 0 0 0-1 1z" />
    <path d="M15 8a4 4 0 0 1 0 8" />
    <path d="M18 5a8 8 0 0 1 0 14" />
  </Svg>
);

export const IconTag = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12.5 3H5a1 1 0 0 0-1 1v7.5a1 1 0 0 0 .3.7l9 9a1 1 0 0 0 1.4 0l7.5-7.5a1 1 0 0 0 0-1.4l-9-9a1 1 0 0 0-.7-.3z" />
    <circle cx="8.5" cy="8.5" r="1.3" fill="currentColor" stroke="none" />
  </Svg>
);

export const IconHelpCircle = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M9.5 9.2a2.5 2.5 0 1 1 3.6 2.2c-.9.5-1.3 1-1.3 2" />
    <line x1="12" y1="17" x2="12" y2="17.01" />
  </Svg>
);

export const IconImage = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <circle cx="9" cy="10" r="1.6" />
    <path d="M21 16.5l-5.5-5.5a1.5 1.5 0 0 0-2.1 0L4 20" />
  </Svg>
);

export const IconFolder = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 6.5A1.5 1.5 0 0 1 5 5h4.5l2 2.5H19a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 19 19.5H5A1.5 1.5 0 0 1 3.5 18v-11.5z" />
  </Svg>
);

export const IconReceipt = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 3h12v18l-2.5-1.5L13 21l-2.5-1.5L8 21l-2-1.5V3z" />
    <path d="M9 8h6M9 12h6M9 16h4" />
  </Svg>
);

export const IconUsers = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="9" cy="8" r="3.2" />
    <path d="M3 20v-1.5A4.5 4.5 0 0 1 7.5 14h3A4.5 4.5 0 0 1 15 18.5V20" />
    <path d="M16.5 8.3a3 3 0 1 1 .5 6" />
    <path d="M17.5 14.2a4.3 4.3 0 0 1 3.5 4.3V20" />
  </Svg>
);

export const IconMessageCircle = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20.5 11.5a8.5 7 0 0 1-8.5 7 9 7.4 0 0 1-3-.5L4 19.5l1.3-3.4A6.9 5.7 0 0 1 3.5 11.5a8.5 7 0 0 1 8.5-7 8.5 7 0 0 1 8.5 7z" />
  </Svg>
);

export const IconMonitor = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="4" width="18" height="12" rx="1.5" />
    <path d="M8 20h8M12 16v4" />
  </Svg>
);

export const IconShieldSearch = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3l7 3v5.5c0 4.6-3 8-7 9.5-4-1.5-7-4.9-7-9.5V6l7-3z" />
    <path d="M9.5 12.2l1.8 1.8 3.2-3.6" />
  </Svg>
);

export const IconSettings = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="3" />
    <path d="M19.4 13a7.8 7.8 0 0 0 .1-2l2-1.5-2-3.5-2.4.8a7.6 7.6 0 0 0-1.7-1l-.4-2.5H9l-.4 2.5a7.6 7.6 0 0 0-1.7 1l-2.4-.8-2 3.5L4.5 11a7.8 7.8 0 0 0 0 2l-2 1.5 2 3.5 2.4-.8c.5.4 1.1.8 1.7 1l.4 2.5h6l.4-2.5c.6-.2 1.2-.6 1.7-1l2.4.8 2-3.5-2-1.5z" />
  </Svg>
);

export const IconCheckCircle = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M8.5 12.3l2.4 2.4 4.6-5.2" />
  </Svg>
);

export const IconLink = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9.5 14.5l5-5" />
    <path d="M8 16.5l-1.6 1.6a3.5 3.5 0 0 1-5-5L5 9.5" />
    <path d="M16 7.5l1.6-1.6a3.5 3.5 0 0 1 5 5L19 14.5" />
  </Svg>
);

export const IconDollarSign = (p: IconProps) => (
  <Svg {...p}>
    <line x1="12" y1="2" x2="12" y2="22" />
    <path d="M17 6.5c0-2-2-3-5-3s-5 1.3-5 3.2c0 4.3 10 2 10 6.3 0 2-2 3.3-5 3.3s-5-1.2-5-3.3" />
  </Svg>
);

export const IconBed = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3 18v-8a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v3" />
    <path d="M3 13h16a2 2 0 0 1 2 2v3" />
    <path d="M3 18v2M21 18v2" />
    <circle cx="7" cy="11" r="1.3" />
  </Svg>
);

export const IconCalendar = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3.5" y="5" width="17" height="16" rx="2" />
    <path d="M3.5 9.5h17" />
    <path d="M8 3v4M16 3v4" />
  </Svg>
);

export const IconMail = (p: IconProps) => (
  <Svg {...p}>
    <rect x="3" y="5" width="18" height="14" rx="2" />
    <path d="M3.5 6.5 12 13l8.5-6.5" />
  </Svg>
);

export const IconGlobe = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M3 12h18" />
    <path d="M12 3c2.5 2.5 3.8 5.7 3.8 9s-1.3 6.5-3.8 9c-2.5-2.5-3.8-5.7-3.8-9s1.3-6.5 3.8-9z" />
  </Svg>
);

export const IconXCircle = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M9.5 9.5l5 5M14.5 9.5l-5 5" />
  </Svg>
);

export const IconTrendingUp = (p: IconProps) => (
  <Svg {...p}>
    <polyline points="3.5,17 9.5,11 13.5,15 20.5,7" />
    <polyline points="15,7 20.5,7 20.5,12.5" />
  </Svg>
);

export const IconStore = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 9.5 5 4h14l1 5.5" />
    <path d="M4 9.5a2.5 2.5 0 0 0 5 0 2.5 2.5 0 0 0 5 0 2.5 2.5 0 0 0 5 0" />
    <path d="M5.5 10.5V20h13v-9.5" />
    <path d="M10 20v-5h4v5" />
  </Svg>
);

export const IconTruck = (p: IconProps) => (
  <Svg {...p}>
    <rect x="2" y="7" width="12" height="9" rx="1" />
    <path d="M14 10.5h4l3 3V16h-7z" />
    <circle cx="6.5" cy="18" r="1.6" />
    <circle cx="17" cy="18" r="1.6" />
  </Svg>
);

export const IconUser = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="8" r="3.5" />
    <path d="M4.5 20v-1.2A5.5 5.5 0 0 1 10 13.3h4a5.5 5.5 0 0 1 5.5 5.5V20" />
  </Svg>
);

export const IconFileText = (p: IconProps) => (
  <Svg {...p}>
    <path d="M7 3h7l5 5v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
    <path d="M14 3v5h5" />
    <path d="M9 13h6M9 16.5h6M9 9.5h2" />
  </Svg>
);

export const IconStar = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3.3l2.6 5.4 5.9.8-4.3 4.2 1 5.9L12 16.6l-5.2 2.9 1-5.9-4.3-4.2 5.9-.8L12 3.3z" />
  </Svg>
);

export const IconKey = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="7.5" cy="14.5" r="3.7" />
    <path d="M10 12l8.5-8.5" />
    <path d="M15.5 6.5l2.3 2.3M18.5 3.5l2.3 2.3" />
  </Svg>
);

export const IconDownload = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3v12" />
    <polyline points="7,10.5 12,15.5 17,10.5" />
    <path d="M4 19.5h16" />
  </Svg>
);

export const IconAlertTriangle = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3.5 21.5 20h-19L12 3.5z" />
    <path d="M12 10v4" />
    <line x1="12" y1="17" x2="12" y2="17.01" />
  </Svg>
);

export const IconFlask = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9.5 3h5" />
    <path d="M10.5 3v6.5L4.8 18.6a1.3 1.3 0 0 0 1.1 2h12.2a1.3 1.3 0 0 0 1.1-2L13.5 9.5V3" />
    <path d="M8 15h8" />
  </Svg>
);

export const IconCompass = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M15.5 8.5l-2 5-5 2 2-5 5-2z" />
  </Svg>
);

export const IconEdit = (p: IconProps) => (
  <Svg {...p}>
    <path d="M14.5 4.5l5 5L8 21H3v-5L14.5 4.5z" />
    <path d="M12.5 6.5l5 5" />
  </Svg>
);

export const IconRotateCcw = (p: IconProps) => (
  <Svg {...p}>
    <path d="M3.5 12a8.5 8.5 0 1 0 2.8-6.3" />
    <polyline points="3,4 3.5,9.5 9,9" />
  </Svg>
);

export const IconCheck = (p: IconProps) => (
  <Svg {...p}>
    <polyline points="4,12.5 9,17.5 20,6" />
  </Svg>
);

export const IconX = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 5l14 14M19 5 5 19" />
  </Svg>
);

export const IconCart = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="9" cy="20" r="1.4" />
    <circle cx="17" cy="20" r="1.4" />
    <path d="M2.5 3h2.5l2.6 12.4a2 2 0 0 0 2 1.6h7.4a2 2 0 0 0 2-1.6L21 7.5H6" />
  </Svg>
);

export const IconWave = (p: IconProps) => (
  <Svg {...p}>
    <path d="M8 11.5V6a1.5 1.5 0 0 1 3 0v4" />
    <path d="M11 10V4.5a1.5 1.5 0 0 1 3 0V10" />
    <path d="M14 10V5.5a1.5 1.5 0 0 1 3 0V13" />
    <path d="M17 9.5a1.5 1.5 0 0 1 3 0V14a7 7 0 0 1-7 7h-1.5a6 6 0 0 1-5-2.7L4 14.8a1.4 1.4 0 0 1 2.3-1.6L8 15" />
  </Svg>
);

export const IconSparkles = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3l1.3 4.2L17.5 8.5l-4.2 1.3L12 14l-1.3-4.2L6.5 8.5l4.2-1.3L12 3z" />
    <path d="M19 14l.7 2.3L22 17l-2.3.7L19 20l-.7-2.3L16 17l2.3-.7L19 14z" />
    <path d="M5 15l.6 1.9L7.5 17.5l-1.9.6L5 20l-.6-1.9L2.5 17.5l1.9-.6L5 15z" />
  </Svg>
);

export const IconHourglass = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 3h12M6 21h12" />
    <path d="M7 3v3.5a5 5 0 0 0 2.2 4.1L11 12l-1.8 1.4A5 5 0 0 0 7 17.5V21" />
    <path d="M17 3v3.5a5 5 0 0 1-2.2 4.1L13 12l1.8 1.4a5 5 0 0 1 2.2 4.1V21" />
  </Svg>
);

export const IconPlay = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6.5 4.5v15l12-7.5-12-7.5z" />
  </Svg>
);

export const IconShieldCheck = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3l7 3v5c0 4.5-2.9 8.3-7 9.5-4.1-1.2-7-5-7-9.5V6l7-3z" />
    <path d="M9 12l2 2 4-4" />
  </Svg>
);

export const IconLock = (p: IconProps) => (
  <Svg {...p}>
    <rect x="5" y="11" width="14" height="9" rx="2" />
    <path d="M8 11V7a4 4 0 0 1 8 0v4" />
  </Svg>
);

export const IconZap = (p: IconProps) => (
  <Svg {...p}>
    <path d="M13 3L5 13.5h5.5L11 21l8-10.5h-5.5L13 3z" />
  </Svg>
);

export const IconBarChart = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 20V10" />
    <path d="M11 20V4" />
    <path d="M18 20v-7" />
  </Svg>
);

export const IconArrowRight = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 12h14" />
    <path d="M13 6l6 6-6 6" />
  </Svg>
);

export const IconMapPinSmall = IconMapPin;
