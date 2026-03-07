export async function POST(request: Request) {
  try {
    const { listingId, userMessage } = await request.json();

    const encoder = new TextEncoder();
    
    // Create a streaming response
    const stream = new ReadableStream({
      async start(controller) {
        // Simulate thinking before streaming
        await new Promise(resolve => setTimeout(resolve, 600));

        const responseText = `That's a great question about ${userMessage.toLowerCase().includes('price') ? 'the price' : 'this car'} (ID: ${listingId}). ` +
          `Based on our analysis, this is a solid choice. The numbers look good given the current market, ` +
          `and its reliability score is in range. \n\nHowever, always make sure to ask for maintenance records before purchasing. ` +
          `Do you want to know more about similar cars, or do you want negotiation tips?`;
          
        // Stream it back word by word over naive SSE chunking
        const words = responseText.split(' ');
        for (const word of words) {
          const chunk = `data: ${JSON.stringify({ text: word + ' ' })}\n\n`;
          controller.enqueue(encoder.encode(chunk));
          await new Promise(resolve => setTimeout(resolve, 30)); // fast typing simulation
        }
        
        controller.enqueue(encoder.encode('data: [DONE]\n\n'));
        controller.close();
      }
    });

    return new Response(stream, {
      headers: {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache, no-transform',
        'Connection': 'keep-alive',
      },
    });
  } catch(error) {
     return new Response(JSON.stringify({ error: 'failed' }), { status: 500 });
  }
}
