<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class SellOrder extends Model
{
    protected $connection = 'exchange';
    protected $table = 'sell_orders';
    public $timestamps = false;
    protected $guarded = ['*'];
}
