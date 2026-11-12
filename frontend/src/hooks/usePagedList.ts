import { useInfiniteQuery } from "@tanstack/react-query";
import { http, type Page } from "@/lib/api";

/**
 * Cursor pagination, the way the backend does it: each response has `next_cursor`;
 * we send it back as `?cursor=` to get the next page. No page numbers, so it stays fast at 1M+ rows.
 */
export function usePagedList<T>(key: string, path: string, params: Record<string, unknown>) {
  const query = useInfiniteQuery({
    queryKey: [key, params],
    initialPageParam: null as string | null,
    queryFn: async ({ pageParam }) => {
      const clean = Object.fromEntries(Object.entries({ ...params, cursor: pageParam, limit: 50 }).filter(([, v]) => v !== undefined && v !== null && v !== ""));
      return (await http.get<Page<T>>(path, { params: clean })).data;
    },
    getNextPageParam: (last) => last.next_cursor,
  });
  const rows = query.data?.pages.flatMap((p) => p.items) ?? [];
  return { ...query, rows };
}
