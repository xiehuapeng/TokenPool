export function createLatestRequest(
  setLoading: (loading: boolean) => void,
  onError: (error: unknown) => void,
) {
  let generation = 0;

  return {
    async run<T>(request: () => Promise<T>, accept: (result: T) => void) {
      const current = ++generation;
      setLoading(true);
      try {
        const result = await request();
        if (current === generation) accept(result);
      } catch (error) {
        if (current === generation) onError(error);
      } finally {
        if (current === generation) setLoading(false);
      }
    },
    invalidate() {
      generation += 1;
      setLoading(false);
    },
  };
}
