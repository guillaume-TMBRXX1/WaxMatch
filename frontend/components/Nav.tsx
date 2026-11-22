"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export const NAV_ITEMS = [
  { href: "/", label: "Accueil", short: "Accueil" },
  { href: "/bibliotheque", label: "Bibliothèque", short: "Biblio" },
  { href: "/affaires", label: "Affaires", short: "Affaires" },
  { href: "/revente", label: "Revente", short: "Revente" },
  { href: "/favoris", label: "Favoris", short: "Favoris" },
  { href: "/reglages", label: "Réglages", short: "Réglages" },
];

function isActive(pathname: string, href: string) {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

export function DesktopNav() {
  const pathname = usePathname();
  return (
    <nav className="nav segmented" aria-label="Navigation principale">
      {NAV_ITEMS.map((item) => (
        <Link key={item.href} href={item.href} aria-current={isActive(pathname, item.href) ? "page" : undefined}>
          {item.label}
        </Link>
      ))}
    </nav>
  );
}

export function MobileNav() {
  const pathname = usePathname();
  return (
    <nav className="nav-mobile glass" aria-label="Navigation">
      {NAV_ITEMS.filter((item) => item.href !== "/").map((item) => (
        <Link key={item.href} href={item.href} aria-current={isActive(pathname, item.href) ? "page" : undefined}>
          {item.short}
        </Link>
      ))}
    </nav>
  );
}
