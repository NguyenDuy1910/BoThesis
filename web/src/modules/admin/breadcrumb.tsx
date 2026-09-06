"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";

interface BreadcrumbValue {
  detailTitle?: string;
  setDetailTitle: (title: string | undefined) => void;
}

const BreadcrumbContext = createContext<BreadcrumbValue | null>(null);

/**
 * Detail pages know the name of the record they are showing; the header does
 * not. This lets the trail end in "Product handbook" rather than "Details",
 * without the header having to fetch the record a second time.
 */
export function AdminBreadcrumbProvider({ children }: { children: React.ReactNode }) {
  const [detailTitle, setDetailTitle] = useState<string | undefined>();
  const value = useMemo(
    () => ({ detailTitle, setDetailTitle }),
    [detailTitle],
  );
  return (
    <BreadcrumbContext.Provider value={value}>{children}</BreadcrumbContext.Provider>
  );
}

export function useAdminBreadcrumb() {
  const value = useContext(BreadcrumbContext);
  if (!value) {
    throw new Error("useAdminBreadcrumb must be used inside AdminBreadcrumbProvider");
  }
  return value;
}

/** Publishes the current record's name for as long as the page is mounted. */
export function useBreadcrumbDetail(title: string | undefined) {
  const { setDetailTitle } = useAdminBreadcrumb();
  useEffect(() => {
    setDetailTitle(title);
    return () => setDetailTitle(undefined);
  }, [setDetailTitle, title]);
}
