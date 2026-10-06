export const CATEGORY_TAGS={
  digital_planner:['digital planner','ipad planner','goodnotes planner','daily planner','weekly planner','monthly planner','productivity','hyperlinked pdf','planner template','digital journal','life planner','instant download','planner bundle'],
  business_finance:['bookkeeping sheet','expense tracker','income tracker','profit tracker','tax organizer','mileage log','invoice tracker','small business','etsy seller','excel template','business finance','digital download','spreadsheet'],
  finance_spreadsheet:['budget spreadsheet','debt payoff','debt snowball','savings tracker','budget planner','money tracker','cash stuffing','bill tracker','finance planner','excel budget','digital budget','instant download','spreadsheet'],
  spreadsheet_bundle:['wedding planner','guest list','rsvp tracker','seating chart','wedding budget','vendor tracker','wedding timeline','wedding sheet','bride planner','digital wedding','excel template','instant download','spreadsheet'],
  education_bundle:['student planner','teacher planner','homeschool planner','grade tracker','assignment tracker','lesson planner','study planner','school planner','education pdf','digital planner','printable planner','instant download','planner bundle'],
  creator_business:['content planner','social media','content calendar','creator planner','hook tracker','content strategy','social planner','post planner','analytics tracker','marketing planner','digital planner','instant download','spreadsheet'],
  career_bundle:['job search','job tracker','application tracker','interview planner','career planner','networking log','offer comparison','job spreadsheet','career template','job hunt','digital download','excel template','tracker'],
  business_forms:['business forms','client intake','service agreement','pricing sheet','client tracker','small business','service business','business template','fillable pdf','business bundle','instant download','client forms','spreadsheet'],
  kawaii_digital_stickers:['digital stickers','goodnotes stickers','kawaii sticker','cute clipart','png stickers','digital planner','food sticker','kawaii clipart','instant download','sticker pack','planner stickers','cute png','digital download'],
  clipart_bundle:['clipart bundle','digital stickers','png bundle','kawaii clipart','goodnotes sticker','cute png','digital planner','instant download','sticker pack','character clipart','planner sticker','digital download','printable sticker'],
  digital_wall_art_bundle:['printable wall art','digital wall art','gallery wall','instant download','printable art','wall art bundle','digital prints','home decor','printable poster','art bundle','downloadable art','gallery prints','digital download'],
  professional_printable_bundle:['nurse report sheet','nursing brain sheet','shift report','sbar template','nurse printable','rn report sheet','nursing student','clinical sheet','printable pdf','nurse planner','digital download','report bundle','med pass sheet'],
  pet_bundle:['pet planner','puppy planner','pet health','dog planner','vaccine tracker','training log','pet printable','new puppy','dog record','pet care','instant download','planner bundle','digital download'],
  health_tracker_bundle:['health tracker','symptom tracker','medical binder','appointment log','wellness tracker','health journal','printable tracker','digital health','personal records','fillable pdf','instant download','tracker bundle','digital download'],
  wellness_bundle:['wellness planner','mood tracker','self care','journal bundle','habit tracker','reflection journal','mental wellness','daily check in','digital journal','printable journal','instant download','planner bundle','digital download'],
  home_bundle:['home planner','home binder','cleaning planner','meal planner','family planner','home organizer','household planner','printable binder','digital planner','instant download','planner bundle','home management','digital download'],
  kids_education:['chore chart','reward chart','kids planner','routine chart','family chart','kids printable','behavior chart','responsibility','printable chart','instant download','parent planner','digital download','kids bundle'],
  finance_bundle:['savings challenge','money challenge','savings tracker','budget printable','no spend challenge','money goals','cash stuffing','finance planner','printable bundle','instant download','money tracker','digital download','savings bundle'],
  planner_bundle:['habit tracker','goal planner','planner bundle','daily tracker','productivity','goal setting','printable planner','digital planner','instant download','planner pages','journal bundle','digital download','tracker bundle'],
  seasonal_bundle:['christmas planner','holiday planner','gift tracker','holiday budget','christmas list','holiday organizer','printable planner','seasonal planner','instant download','digital planner','holiday bundle','digital download','christmas printable'],
  event_bundle:['party planner','event planner','guest list','event budget','birthday planner','party checklist','event organizer','printable planner','digital planner','instant download','party bundle','digital download','spreadsheet'],
  journal_bundle:['reading journal','gratitude journal','digital journal','book tracker','journal printable','reflection journal','planner bundle','instant download','journal pages','printable journal','digital download','book planner','journal bundle'],
  family_bundle:['pregnancy planner','baby tracker','family planner','appointment log','newborn tracker','baby planner','printable planner','digital planner','instant download','family organizer','planner bundle','digital download','tracker bundle'],
  garden_bundle:['garden planner','plant tracker','planting calendar','harvest tracker','garden journal','vegetable garden','plant care','digital planner','printable planner','instant download','garden bundle','digital download','garden log'],
  travel_bundle:['travel planner','trip planner','itinerary','travel budget','packing list','vacation planner','travel organizer','digital planner','printable planner','instant download','travel bundle','digital download','trip itinerary'],
  fitness_bundle:['fitness planner','workout log','gym tracker','exercise log','progress tracker','fitness journal','digital planner','printable planner','instant download','workout planner','digital download','fitness bundle','health tracker'],
  digital_bundle:['digital planner','printable bundle','instant download','planner template','digital download','organizer','tracker','workbook','planner pages','digital file','template bundle','productivity','printable']
};

export const CATEGORY_PRICE={
  digital_planner:9.99,business_finance:12.99,finance_spreadsheet:11.99,spreadsheet_bundle:12.99,
  education_bundle:9.99,creator_business:11.99,career_bundle:9.99,business_forms:12.99,
  kawaii_digital_stickers:4.99,clipart_bundle:5.99,digital_wall_art_bundle:8.99,
  professional_printable_bundle:8.99,pet_bundle:8.99,health_tracker_bundle:8.99,
  wellness_bundle:8.99,home_bundle:9.99,kids_education:5.99,finance_bundle:7.99,
  planner_bundle:7.99,seasonal_bundle:8.99,event_bundle:8.99,journal_bundle:7.99,
  family_bundle:8.99,garden_bundle:7.99,travel_bundle:8.99,fitness_bundle:8.99,digital_bundle:6.99
};

export function normalizeTags(category){
  const src=CATEGORY_TAGS[category]||CATEGORY_TAGS.digital_bundle;
  return [...new Set(src.map(x=>x.slice(0,20)))].slice(0,13);
}
export function titleFor(product){
  const s=String(product).replaceAll('—','-').trim();
  if(s.length<=118) return s;
  return s.slice(0,115).replace(/\s+\S*$/,'');
}
export function descriptionFor(product,category){
  const specific={
    digital_planner:'A reusable digital planning system built around daily, weekly, monthly and review workflows.',
    business_finance:'A bookkeeping system for income, expenses, mileage, invoices and profit review.',
    finance_spreadsheet:'A money dashboard for budgeting, debt payoff, savings and bill tracking.',
    spreadsheet_bundle:'A wedding planning system for guest list, RSVP, seating, vendors, budget and timeline.',
    creator_business:'A content planning and performance system for creators and small businesses.',
    career_bundle:'A job-search dashboard for applications, networking, interviews and offer comparison.',
    business_forms:'A practical client-management and pricing system for service businesses.',
    kawaii_digital_stickers:'An original kawaii digital sticker and clipart pack for digital planners, notes and personal creative projects.',
    clipart_bundle:'An original character clipart and digital sticker bundle for planners and personal creative projects.',
    digital_wall_art_bundle:'A coordinated printable wall-art collection delivered digitally; print at home or through your preferred print service.'
  }[category]||'A deeper digital bundle with reusable pages and trackers designed around this specific buyer need.';
  return `${product}

DIGITAL DOWNLOAD — NO PHYSICAL ITEM

${specific}

WHAT YOU RECEIVE
• Original CYZOR Creations digital files for this product.
• Instant delivery through Etsy after payment confirmation.
• Reusable personal-use files unless the listing explicitly states a different license.

HOW IT WORKS
1. Purchase on Etsy.
2. Download from your Etsy order after payment is confirmed.
3. Open digitally, print, or use the spreadsheet/PDF format described in the listing.
4. Reuse the included templates for your own personal workflow.

WHY THIS VERSION
• Built around one clear buyer job-to-be-done.
• Deeper, more useful structure instead of a shallow filler printable.
• Clear digital delivery — no shipping, no POD.
• Original CYZOR layout and copy.

IMPORTANT
• Nothing will be mailed.
• Colors can vary by screen and printer.
• Health, finance, legal, tax and business templates are organizational tools only and are not professional advice.
• No resale, redistribution, sublicensing or claiming the files as your own unless a separate commercial license is explicitly included.

SUPPORT
If you have trouble accessing your files, message CyzorCreations through Etsy with the listing name.`;
}
export function patchFromRebuild(item){
  return {
    listing_id:String(item.listing_id),
    product:item.new_product,
    category:item.category,
    conversion_priority:item.conversion_priority,
    type:'download',
    title:titleFor(item.new_product),
    description:descriptionFor(item.new_product,item.category),
    tags:normalizeTags(item.category),
    price:CATEGORY_PRICE[item.category]||6.99
  };
}
