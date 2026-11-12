import { PageHeader } from "./PageHeader";
import { Card, CardContent } from "@/components/ui/card";

export function ComingSoon({ title, note }: { title: string; note?: string }) {
  return (
    <>
      <PageHeader title={title} />
      <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">{note ?? "This screen is built in a later step."}</CardContent></Card>
    </>
  );
}
