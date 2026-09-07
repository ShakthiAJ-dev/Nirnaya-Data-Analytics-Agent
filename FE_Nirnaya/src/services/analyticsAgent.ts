import type { Message, FileAttachment, TableData } from '../types';

export async function generateAnalyticsResponse(
  prompt: string,
  projectName: string,
  files: FileAttachment[],
  modelId: string,
  onStreamUpdate?: (partialText: string) => void
): Promise<Partial<Message>> {
  // Normalize prompt
  const lower = prompt.toLowerCase();

  // Intelligent mock response template tailored to data analytics
  let content = '';
  let sqlQuery: string | undefined;
  let tableData: TableData | undefined;
  let insights: string[] = [];
  let suggestions: string[] = [];

  const filesSummary = files.length > 0
    ? `analyzing ${files.map((f) => f.name).join(', ')} alongside ${projectName}`
    : `querying project repository: ${projectName}`;

  if (lower.includes('churn') || lower.includes('retention')) {
    content = `Based on our multi-cohort retention model for **${projectName}**, we observe a statistically significant drop-off occurring between Month 2 and Month 3 (38% churn cliff). The primary contributing factor is low feature adoption in the first 14 days following onboarding.`;
    
    sqlQuery = `SELECT 
    cohort_month,
    COUNT(DISTINCT user_id) AS total_users,
    ROUND(SUM(CASE WHEN days_active >= 30 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS m1_retention_pct,
    ROUND(SUM(CASE WHEN days_active >= 60 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS m2_retention_pct,
    ROUND(SUM(CASE WHEN days_active >= 90 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS m3_retention_pct
FROM user_activity_events
WHERE project_id = '${projectName.toLowerCase().replace(/\s+/g, '_')}'
GROUP BY cohort_month
ORDER BY cohort_month DESC
LIMIT 4;`;

    tableData = {
      title: 'Customer Cohort Retention Breakdown (%)',
      headers: ['Cohort Month', 'Active Users', 'Month 1 (%)', 'Month 2 (%)', 'Month 3 (%)'],
      rows: [
        ['2026-05', '1,420', '84.2%', '68.5%', '42.1%'],
        ['2026-06', '1,680', '86.0%', '71.2%', '45.8%'],
        ['2026-07', '1,950', '88.4%', '74.1%', '48.2%'],
        ['2026-08', '2,110', '89.1%', '76.8%', '51.0%'],
      ],
    };

    insights = [
      'Proactive check-ins triggered on Day 18 reduce Month 3 churn risk by 24%.',
      'Users who export or schedule at least 2 analytical reports exhibit 3.2x higher Lifetime Value (LTV).',
      'Recommended Action (Nirnaya): Deploy automated onboarding milestone notifications for dormant cohort accounts.',
    ];

    suggestions = [
      'What are the primary churn triggers for high-tier accounts?',
      'Forecast revenue impact if M3 retention improves by 5%',
      'Generate Python script for churn survival curve',
    ];
  } else if (lower.includes('revenue') || lower.includes('sales') || lower.includes('margin') || lower.includes('profit')) {
    content = `Analyzing quarterly metrics for **${projectName}**: Overall gross revenue climbed to **$1,480,000** (+18.4% QoQ), while blended gross margin tightened by 1.8% due to higher outbound logistics fulfillment costs.`;

    sqlQuery = `SELECT 
    product_category,
    SUM(gross_revenue) AS total_revenue,
    ROUND(AVG(gross_margin_pct), 2) AS avg_margin_pct,
    SUM(order_count) AS total_orders,
    ROUND(SUM(gross_revenue) / SUM(order_count), 2) AS aov
FROM sales_transactions
WHERE date_trunc('quarter', transaction_date) = '2026-Q3'
GROUP BY product_category
ORDER BY total_revenue DESC;`;

    tableData = {
      title: 'Q3 Category Revenue & Margin Summary',
      headers: ['Category', 'Gross Revenue', 'Avg Margin', 'Orders', 'AOV'],
      rows: [
        ['Enterprise Suite', '$680,000', '78.4%', '420', '$1,619.00'],
        ['Pro Subscriptions', '$440,000', '82.1%', '2,200', '$200.00'],
        ['Add-on Services', '$240,000', '52.3%', '860', '$279.00'],
        ['Custom Integrations', '$120,000', '64.0%', '45', '$2,666.00'],
      ],
    };

    insights = [
      'Enterprise Suite is the dominant growth engine, contributing 46% of aggregate revenue.',
      'Add-on Services margin softened by 420 bps; price optimization review advised.',
      'Recommended Action (Nirnaya): Re-evaluate SLA tier pricing to safeguard gross margin above target 75%.',
    ];

    suggestions = [
      'Breakdown revenue by regional sales territory',
      'Calculate customer acquisition cost (CAC) payback period',
      'Simulate a 10% price increase on Add-on Services',
    ];
  } else if (files.length > 0) {
    content = `I have ingested and processed your uploaded dataset (${files.map((f) => f.name).join(', ')}). The schema was automatically parsed, type-checked, and cross-referenced with your **${projectName}** workspace.`;

    sqlQuery = `-- Auto-generated exploratory profiling
SELECT 
    column_name,
    data_type,
    null_count,
    ROUND(null_count * 100.0 / total_rows, 2) AS null_pct,
    distinct_values
FROM sys_dataset_profiler
WHERE dataset_name = '${files[0].name}'
ORDER BY null_pct DESC;`;

    tableData = {
      title: `Dataset Overview: ${files[0].name}`,
      headers: ['Column', 'Type', 'Non-Null Rows', 'Unique Values', 'Quality Score'],
      rows: [
        ['record_id', 'UUID', '14,250 / 14,250', '14,250', '100% Valid'],
        ['timestamp_utc', 'TIMESTAMP', '14,250 / 14,250', '13,820', '100% Valid'],
        ['segment_category', 'VARCHAR', '14,110 / 14,250', '8', '99.0% Valid'],
        ['metric_value', 'FLOAT8', '13,990 / 14,250', '6,450', '98.2% Valid'],
      ],
    };

    insights = [
      `File "${files[0].name}" contains 14,250 records across 18 features with 99.1% completeness.`,
      'No critical schema conflicts detected with existing project dimensional tables.',
      'Recommended Action (Nirnaya): Ready for immediate regression modeling, segmentation, or anomaly scan.',
    ];

    suggestions = [
      'Run automated anomaly detection on metric_value',
      'Correlate segment_category with quarterly performance',
      'Export clean dataset with imputed missing values',
    ];
  } else {
    content = `I analyzed your inquiry against the **${projectName}** data environment using **${modelId}** (${filesSummary}). Here is the decision-grade analytical summary and query strategy:`;

    sqlQuery = `SELECT 
    DATE_TRUNC('month', created_at) AS time_bucket,
    segment_group,
    COUNT(*) AS event_count,
    ROUND(AVG(performance_index), 2) AS avg_index
FROM project_metrics
WHERE active = true
GROUP BY 1, 2
ORDER BY 1 DESC, 4 DESC
LIMIT 5;`;

    tableData = {
      title: 'Target Segment Performance Matrix',
      headers: ['Time Bucket', 'Segment Group', 'Event Count', 'Performance Index'],
      rows: [
        ['2026-08', 'Alpha Tier', '4,890', '94.6'],
        ['2026-08', 'Beta Tier', '8,120', '88.2'],
        ['2026-07', 'Alpha Tier', '4,610', '92.1'],
        ['2026-07', 'Beta Tier', '7,900', '86.4'],
        ['2026-06', 'Alpha Tier', '4,300', '89.5'],
      ],
    };

    insights = [
      'Alpha tier accounts demonstrate 6.8% month-over-month performance acceleration.',
      'Beta tier volume expanded by 12%, showing steady adoption across core segments.',
      'Strategic Decision (Nirnaya): Focus incentive programs on elevating Beta tier participants into Alpha status.',
    ];

    suggestions = [
      'Drill down into Alpha Tier geographic distribution',
      'Compare performance index against historical 2025 benchmarks',
      'Generate executive slide summary for leadership team',
    ];
  }

  // Simulate streaming delay for ultra-realistic UX
  if (onStreamUpdate) {
    const words = content.split(' ');
    let accumulated = '';
    for (let i = 0; i < words.length; i++) {
      accumulated += (i === 0 ? '' : ' ') + words[i];
      onStreamUpdate(accumulated);
      await new Promise((r) => setTimeout(r, 20));
    }
  }

  return {
    content,
    sqlQuery,
    tableData,
    insights,
    suggestions,
    model: modelId,
  };
}
