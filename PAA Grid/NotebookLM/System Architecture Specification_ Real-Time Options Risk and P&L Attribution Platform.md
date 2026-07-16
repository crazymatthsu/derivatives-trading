### System Architecture Specification: Real-Time Options Risk and P\&L Attribution Platform

#### 1\. Architectural Mission and Strategic Context

The strategic necessity of a real-time risk and P\&L Attribution (PAA) system lies in the establishment of a singular "ground truth" across the enterprise. In institutional trading, temporal alignment is the foundation of trust; without rigorous synchronization between market states and book positions, the resulting analytics lack the precision required for high-stakes decision-making. This platform must ensure that the financial narrative of the trading book is mathematically defensible and consistent across all desks.The architecture must support two distinct but interconnected analytical mandates.  **Risk Management**  is inherently forward-looking, utilizing current Greeks to quantify potential exposure and inform hedging strategies. Conversely,  **P\&L Attribution (PAA)**  is backward-looking, designed to decompose the daily change in book value into its constituent Greek components (e.g., Delta P\&L, Vega P\&L). The system’s primary objective is to minimize "unexplained P\&L," as high residuals signal a breakdown in model integrity or data synchronization, which erodes model validation confidence and triggers regulatory scrutiny. The complexity of this alignment is dictated largely by the exercise style of the underlying options, requiring a data architecture that adapts to the specific risk dynamics of different global markets.

#### 2\. Theoretical Foundation: American vs. European Risk Dynamics

The underlying exercise style of an option dictates the required precision of the data architecture. While European-style options—prevalent in the Japanese markets (e.g., Nikkei 225 on the Osaka Exchange)—allow for a "cleaner" attribution due to fixed exercise dates, American-style options—dominant in US single-stock markets—introduce non-linearities that demand stricter timestamp synchronization.

##### Comparison of Option Dynamics

Feature,"European Options (e.g., Japan/Nikkei)","American Options (e.g., US Single Stocks)"  
Exercise Window,Only at expiration.,Anytime up to and including expiration.  
Valuation Model,"Analytical (e.g., Black-Scholes).","Iterative (e.g., Binomial/Trinomial trees)."  
Implied Volatility,Backed out from analytical formulas.,Iterated from tree-based models.  
P\&L Attribution,High explainability; linear Greek decay.,Higher residuals due to early exercise premiums.  
Sensitivity,Smooth; primarily spot/vol driven.,Highly sensitive to borrow costs and dividends.

##### The Impact of Early Exercise and Borrow Costs

For American options, the "Early Exercise Premium" complicates standard Greek capture. The architecture must account for  **Put-Call Parity**  imbalances, particularly in stocks with high borrowing costs (hard-to-borrow). High borrow costs act as a friction for market makers who must short the underlying to hedge calls; this cost is passed to the option price, making calls structurally "cheaper" (undervalued) and puts "richer." Because standard Greeks often fail to capture this friction perfectly, the system must use implied volatility trees to approximate these values, or residuals will spike.

##### Architectural Rationale: Strategic Impact of Residuals

The system shall target specific "unexplained P\&L" thresholds to maintain model confidence. For European index books, residuals must remain between  **10–15%** . For American single-stock books, residuals of  **20–30%**  are acceptable due to the early exercise effect. Any deviation beyond these limits indicates a failure in the timestamp alignment of marks, Greeks, or positions, necessitating a strict "atomic" approach to data messaging.

#### 3\. Data Entity Definitions and Governance

A "Golden Source" for market data and quantitative outputs is a non-negotiable requirement to prevent "noisy" P\&L fluctuations.

##### The "Official Mark" Logic

The system shall utilize an  **Official Mark**  as the primary pricing anchor. The Marking Team (or Valuation Desk) must govern this field to resolve wide bid-ask spreads in illiquid instruments.

* **Market Quotes:**  For liquid options, the Official Mark is derived from exchange-quoted mid-prices.  
* **Theoretical Prices:**  For illiquid options (low volume, wide spreads), the system must use the Quant Engine’s theoretical model price as the Official Mark to prevent artificial P\&L volatility.

##### PAA Ladder Greeks and Units

The architecture must support the following Greeks, ensuring data types accommodate their specific units of measure:

* **Delta:**  Sensitivity to a $1 change in the underlying spot price.  
* **Gamma:**  Change in Delta per $1 change in spot.  
* **Vega:**  Change in option price per 1% move in implied volatility ($/Vol Point).  
* **Theta:**  Daily time decay of the option price.  
* **Rho:**  Sensitivity to a 1% change in interest rates.  
* **Vanna:**  Sensitivity of Delta to changes in volatility.  
* **Volga (Vomma):**  Sensitivity of Vega to changes in volatility.

##### Data Item Governance Mapping

Data Item,Primary Source,Responsibility,Primary Use  
Spot Price,Market Data Vendor,Data Engineering,Input for all Greek calculations  
Market Quote,Exchange/Vendor,Data Engineering,Actual P\&L (Liquid assets)  
Official Mark,Marking Team,Valuation Desk,Anchor for P\&L and Vol backing  
Implied Vol,Quant Engine,Quant Team,Iterated from Official Mark  
Greeks,Quant Engine,Quant Team,Risk exposure and PAA breakdown  
Position,Trade System,Operations,"Base for ""Position x Greek"" calc"

#### 4\. Dual-Stream Data Architecture and Messaging

To ensure real-time responsiveness without sacrificing mathematical consistency, the architecture shall employ a decoupled, event-driven dual-stream model.

##### Stream 1: Market Data & Risk (The Atomic Requirement)

The Quant Engine shall produce a unified risk stream. It is a  **Hard Requirement**  that the Spot Price, Official Marks, Implied Volatility, and Greeks be bundled into a single  **Atomic Message** . If these components are transmitted via separate threads, micro-movements in the spot price between messages will cause the Greeks to be inconsistent with the marks, creating "phantom" unexplained P\&L.

##### Stream 2: Position & Execution

This stream manages the book’s inventory. It must combine a  **Start-of-Day (SOD) position**  (loaded from the previous day’s closing state) with a real-time  **Execution Record Stream** . The live position is updated incrementally as trades occur.

##### Architectural Rationale: Decoupling Strategy

Separating these streams allows the platform to process high-velocity executions at sub-millisecond speeds while maintaining fixed-interval risk snapshots (e.g., 15-minute snaps). This prevents the computationally expensive Greek engine from becoming a bottleneck to position updates.

#### 5\. Temporal Alignment and Stream Processing (AMPS & Deephaven)

The core technical challenge is the time-series join. The system shall utilize  **AMPS (60East)**  for low-latency messaging and  **Deephaven**  for stream processing and temporal alignment.

##### Logic Flow for Snap-Time Alignment (e.g., 10:00 AM Report)

To ensure the "ground truth" at any given Snap Time  $T$ , the system must execute the following logic:

1. **Trigger Snap:**  At  $T$  (10:00:00 AM), capture the latest  **Atomic Message**  from Stream 1 where the message timestamp  $\\le T$ .  
2. **Position Accumulation:**  Query the Execution Stream and calculate the net position  **as of**   $T$  by summing the SOD position and all executions where the trade timestamp  $\\le T$ .  
3. **Stateful Join:**  Perform a join between the "As of  $T$ " position and the "Snap  $T$ " Greeks using instrument IDs as the primary keys.

##### Memory Efficiency and Keyed Tables

The system shall utilize  **Keyed Tables**  in Deephaven to maintain only the "latest state" of the market and positions. This prevents Out-of-Memory (OOM) risks associated with high-velocity tick data while still allowing the system to perform instantaneous joins at the Snap Time.

#### 6\. Analytical Outputs: The P\&L Ladder and Risk Grid

The architecture transforms synchronized data into two primary outputs for trader intelligence.

##### The P\&L Ladder

The P\&L Ladder explains the daily change in book value.

* **Actual P\&L:**  Calculated as  $(Official Mark\_T \- Official Mark\_{T-1}) \\times Position \+ Cash$ . This is the absolute Mark-to-Market change.  
* **Explained P\&L:**  The summation of all Greek contributions (e.g.,  $\\Delta Spot \\times Delta \\times Position$ ).  
* **Unexplained P\&L:**  The residual difference between Actual and Explained.

##### The Risk Grid and Roll-up Logic

The  **Risk Grid**  provides a forward-looking summary of total exposure. It is derived by calculating  $Position \\times Greek$  for every instrument. The architecture must support a  **Hierarchical Roll-up** , aggregating individual instrument risks upward through the organization:

* **Book Level:**  Granular risk for individual portfolios.  
* **Desk/Strategy Level:**  Aggregated risk for related books.  
* **Firm-wide Level:**  Total net exposure across all business units.By enforcing timestamped synchronization at the atomic level, the platform guarantees that these aggregated views are consistent, providing the firm with an accurate, real-time perspective on its global options exposure.

